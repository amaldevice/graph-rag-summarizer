"""One-off Modal GPU entrypoint for document-safe Ingest Runs."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path, PurePosixPath

import modal


APP_NAME = "graph-rag-ingest"
CACHE_MOUNT = "/cache"
RUN_MOUNT = "/runs"
CACHE_VOLUME_NAME = os.getenv("MODAL_INGEST_CACHE_VOLUME", "graph-rag-ingest-cache")
RUN_VOLUME_NAME = os.getenv("MODAL_INGEST_RUN_VOLUME", "graph-rag-ingest-runs")
SECRET_NAME = os.getenv("MODAL_INGEST_SECRET_NAME", "graph-rag-ingest")
SPACY_MODEL_WHEEL = (
    "https://github.com/explosion/spacy-models/releases/download/"
    "en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl"
)
PROJECT_MODULES = (
    "config",
    "embedding",
    "graph",
    "launcher",
    "preprocessing",
    "storage",
    "summarizer",
    "vectordb",
)


def _build_image() -> modal.Image:
    image = modal.Image.debian_slim(python_version="3.12").uv_sync().workdir("/root/app")
    for module in PROJECT_MODULES:
        image = image.add_local_dir(module, f"/root/app/{module}", copy=True)
    return image.run_commands(
        f"/.uv/uv pip install --python /.uv/.venv/bin/python {SPACY_MODEL_WHEEL}"
    )


app = modal.App(APP_NAME)
image = _build_image()
cache_volume = modal.Volume.from_name(CACHE_VOLUME_NAME, create_if_missing=True)
run_volume = modal.Volume.from_name(RUN_VOLUME_NAME, create_if_missing=True)
cloud_secret = modal.Secret.from_name(SECRET_NAME)


def stage_pdf(volume, local_pdf: Path, *, run_id: str) -> str:
    """Stage a local PDF and return its worker-only path."""
    remote_key = f"/inputs/{run_id}/{local_pdf.name}"
    with volume.batch_upload() as batch:
        batch.put_file(local_pdf, remote_key)
    return f"{RUN_MOUNT}{remote_key}"


def build_remote_ingest_config(
    *,
    collection: str,
    document_id: str,
    ingest_mode: str,
    collection_mode: str,
    enable_graph_artifact: bool,
    verbose: bool,
    staged_pdf_path: str,
    run_id: str,
) -> dict:
    if not collection.strip():
        raise ValueError("collection is required")
    if not document_id.strip():
        raise ValueError("document_id is required")
    if not staged_pdf_path.startswith(f"{RUN_MOUNT}/"):
        raise ValueError("staged_pdf_path must be a Modal worker path")

    return {
        "mode": "ingest",
        "profile": "cloud",
        "collection": collection,
        "collection_mode": collection_mode,
        "pdf_path": staged_pdf_path,
        "verbose": verbose,
        "ingest_mode": ingest_mode,
        "document_id": document_id,
        "enable_graph_artifact": enable_graph_artifact,
        "artifact_dir": f"{RUN_MOUNT}/artifacts/{run_id}",
        "artifact_volume": RUN_VOLUME_NAME,
        "artifact_key": f"artifacts/{run_id}",
        "artifact_location": f"modal-volume://{RUN_VOLUME_NAME}/artifacts/{run_id}",
    }


def _cuda_summary() -> dict:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("Modal GPU is unavailable; refusing to run a CUDA Ingest Run on CPU")
    return {
        "resolved_device": "cuda",
        "gpu_name": torch.cuda.get_device_name(0),
    }


def _run_ingest(config: dict) -> None:
    from launcher.runners import run_ingest

    run_ingest(config)


def _graph_artifact_summary(config: dict, artifact_location: str) -> dict:
    if not config.get("enable_graph_artifact"):
        return {"status": "not-requested"}
    status_path = Path(config["artifact_dir"]) / "graph_artifact_status.json"
    if not status_path.is_file():
        raise RuntimeError("persistent graph status artifact was not written")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if not isinstance(status.get("status"), str):
        raise RuntimeError("persistent graph status artifact is invalid")
    return {
        "status": status["status"],
        "status_location": f"{artifact_location}/graph_artifact_status.json",
        "artifact_key": status.get("artifact_key"),
        "artifact_digest": status.get("artifact_digest"),
    }


def _durable_artifact_location(config: dict) -> str:
    """Derive the reported Volume URI rather than trusting remote input."""
    artifact_volume = config.get("artifact_volume")
    artifact_key = config.get("artifact_key")
    if artifact_volume != RUN_VOLUME_NAME:
        raise ValueError("artifact_volume must be the configured Modal run Volume")
    if not isinstance(artifact_key, str) or not artifact_key:
        raise ValueError("artifact_key must identify a durable Modal Volume path")

    path = PurePosixPath(artifact_key)
    if (
        path.is_absolute()
        or ".." in path.parts
        or len(path.parts) < 2
        or path.parts[0] != "artifacts"
    ):
        raise ValueError("artifact_key must stay below the Modal Volume artifacts prefix")

    artifact_location = f"modal-volume://{RUN_VOLUME_NAME}/{path.as_posix()}"
    supplied_location = config.get("artifact_location")
    if supplied_location is not None and supplied_location != artifact_location:
        raise ValueError("artifact_location must match the durable Modal Volume path")
    return artifact_location


def execute_remote_ingest(config: dict) -> dict:
    """Run the existing Ingest lifecycle and persist a durable result."""
    artifact_location = _durable_artifact_location(config)
    runtime = _cuda_summary()
    _run_ingest(config)
    graph_artifact = _graph_artifact_summary(config, artifact_location)
    result = {
        "mode": "ingest",
        "status": (
            "completed"
            if graph_artifact["status"] in {"available", "not-requested"}
            else "completed-with-graph-unavailable"
        ),
        "collection": config["collection"],
        "document_id": config["document_id"],
        "ingest_mode": config["ingest_mode"],
        "artifact_volume": config["artifact_volume"],
        "artifact_key": config["artifact_key"],
        "artifact_location": artifact_location,
        "graph_artifact": graph_artifact,
        **runtime,
    }
    result_path = Path(config["artifact_dir"]) / "modal_ingest_result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    cache_volume.commit()
    run_volume.commit()
    return result


@app.function(
    image=image,
    gpu="L4",
    timeout=60 * 60,
    secrets=[cloud_secret],
    volumes={CACHE_MOUNT: cache_volume, RUN_MOUNT: run_volume},
    env={
        "LAUNCHER_PROFILE": "cloud",
        "QDRANT_BACKEND": "cloud",
        "STORAGE_BACKEND": "r2",
        "EMBEDDING_DEVICE": "cuda",
        "EMBEDDING_CACHE_ROOT": f"{CACHE_MOUNT}/embedding",
    },
)
def remote_ingest(config: dict) -> dict:
    return execute_remote_ingest(config)


@app.local_entrypoint()
def main(
    pdf: str,
    collection: str,
    document_id: str = "",
    ingest_mode: str = "append",
    collection_mode: str = "document-safe",
    enable_graph_artifact: bool = True,
    verbose: bool = False,
) -> None:
    local_pdf = Path(pdf).expanduser()
    if not local_pdf.is_file():
        raise ValueError(f"PDF file not found: {local_pdf}")

    run_id = uuid.uuid4().hex
    staged_pdf_path = stage_pdf(run_volume, local_pdf, run_id=run_id)
    result = remote_ingest.remote(build_remote_ingest_config(
        collection=collection,
        document_id=document_id or local_pdf.stem,
        ingest_mode=ingest_mode,
        collection_mode=collection_mode,
        enable_graph_artifact=enable_graph_artifact,
        verbose=verbose,
        staged_pdf_path=staged_pdf_path,
        run_id=run_id,
    ))
    print(json.dumps(result, indent=2))
