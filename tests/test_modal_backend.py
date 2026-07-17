import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def test_stage_pdf_returns_only_a_worker_path(tmp_path: Path) -> None:
    import modal_backend

    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    uploaded = []

    class Batch:
        def put_file(self, local_path, remote_path):
            uploaded.append((local_path, remote_path))

    class Upload:
        def __enter__(self):
            return Batch()

        def __exit__(self, *args):
            return False

    class Volume:
        def batch_upload(self):
            return Upload()

    staged_path = modal_backend.stage_pdf(Volume(), source, run_id="run-1")

    assert staged_path == "/runs/inputs/run-1/source.pdf"
    assert uploaded == [(source, "/inputs/run-1/source.pdf")]
    assert str(source) != staged_path


def test_build_remote_ingest_config_keeps_cloud_storage_and_remote_paths() -> None:
    import modal_backend

    config = modal_backend.build_remote_ingest_config(
        collection="disposable",
        document_id="paper-a",
        ingest_mode="replace-document",
        collection_mode="document-safe",
        enable_graph_artifact=True,
        verbose=True,
        staged_pdf_path="/runs/inputs/run-1/source.pdf",
        run_id="run-1",
    )

    assert config["profile"] == "cloud"
    assert config["pdf_path"] == "/runs/inputs/run-1/source.pdf"
    assert config["artifact_dir"] == "/runs/artifacts/run-1"
    assert config["artifact_volume"] == "graph-rag-ingest-runs"
    assert config["artifact_key"] == "artifacts/run-1"
    assert config["artifact_location"] == "modal-volume://graph-rag-ingest-runs/artifacts/run-1"
    assert config["ingest_mode"] == "replace-document"
    assert config["document_id"] == "paper-a"
    assert config["enable_graph_artifact"] is True


def test_remote_execution_commits_a_durable_result(monkeypatch, tmp_path: Path) -> None:
    import modal_backend

    events = []
    monkeypatch.setattr(modal_backend, "_run_ingest", lambda config: events.append(config.copy()))
    monkeypatch.setattr(
        modal_backend,
        "_cuda_summary",
        lambda: {"resolved_device": "cuda", "gpu_name": "NVIDIA L4"},
    )

    class Volume:
        def __init__(self, name):
            self.name = name

        def commit(self):
            events.append(f"commit:{self.name}")

    monkeypatch.setattr(modal_backend, "cache_volume", Volume("cache"))
    monkeypatch.setattr(modal_backend, "run_volume", Volume("runs"))
    artifact_dir = tmp_path / "artifacts"
    result = modal_backend.execute_remote_ingest({
        "collection": "disposable",
        "document_id": "paper-a",
        "ingest_mode": "replace-document",
        "artifact_dir": str(artifact_dir),
        "artifact_volume": "graph-rag-ingest-runs",
        "artifact_key": "artifacts/run-1",
        "artifact_location": "modal-volume://graph-rag-ingest-runs/artifacts/run-1",
    })

    assert events[-2:] == ["commit:cache", "commit:runs"]
    assert result["resolved_device"] == "cuda"
    assert result["artifact_location"] == "modal-volume://graph-rag-ingest-runs/artifacts/run-1"
    assert "artifact_dir" not in result
    assert result["mode"] == "ingest"
    assert result["status"] == "completed"
    assert result["graph_artifact"] == {"status": "not-requested"}
    assert json.loads((artifact_dir / "modal_ingest_result.json").read_text()) == result


def test_remote_execution_reports_unavailable_graph_artifact(monkeypatch, tmp_path: Path) -> None:
    import modal_backend

    artifact_dir = tmp_path / "artifacts"

    def fake_run(config):
        target = Path(config["artifact_dir"])
        target.mkdir(parents=True, exist_ok=True)
        (target / "graph_artifact_status.json").write_text(
            json.dumps({"status": "unavailable", "failure_reason": "provider unavailable"}),
            encoding="utf-8",
        )

    monkeypatch.setattr(modal_backend, "_run_ingest", fake_run)
    monkeypatch.setattr(
        modal_backend,
        "_cuda_summary",
        lambda: {"resolved_device": "cuda", "gpu_name": "NVIDIA L4"},
    )

    class Volume:
        def commit(self):
            pass

    monkeypatch.setattr(modal_backend, "cache_volume", Volume())
    monkeypatch.setattr(modal_backend, "run_volume", Volume())
    result = modal_backend.execute_remote_ingest({
        "collection": "disposable",
        "document_id": "paper-a",
        "ingest_mode": "append",
        "enable_graph_artifact": True,
        "artifact_dir": str(artifact_dir),
        "artifact_volume": "graph-rag-ingest-runs",
        "artifact_key": "artifacts/run-1",
        "artifact_location": "modal-volume://graph-rag-ingest-runs/artifacts/run-1",
    })

    assert result["status"] == "completed-with-graph-unavailable"
    assert result["graph_artifact"] == {
        "status": "unavailable",
        "status_location": "modal-volume://graph-rag-ingest-runs/artifacts/run-1/graph_artifact_status.json",
        "artifact_key": None,
        "artifact_digest": None,
    }
