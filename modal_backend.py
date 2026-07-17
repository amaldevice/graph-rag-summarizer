"""One-off Modal GPU entrypoint for document-safe Ingest Runs."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

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


def execute_remote_ingest(config: dict) -> dict:
    """Run the existing Ingest lifecycle and persist a durable result."""
    runtime = _cuda_summary()
    _run_ingest(config)
    result = {
        "collection": config["collection"],
        "document_id": config["document_id"],
        "ingest_mode": config["ingest_mode"],
        "artifact_dir": config["artifact_dir"],
        **runtime,
    }
    result_path = Path(config["artifact_dir"]) / "modal_ingest_result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
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
