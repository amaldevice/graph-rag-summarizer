# ============================================================
# UPLOAD WRAPPER TESTS
# Legacy upload entrypoint should delegate to shared ingest runner.
# ============================================================

import sys
import importlib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def test_upload_to_qdrant_delegates_to_run_ingest(monkeypatch):
    upload_module = importlib.import_module("upload_to_qdrant")

    monkeypatch.setenv("PDF_PATH", "paper.pdf")
    monkeypatch.setenv("QDRANT_COLLECTION", "manual_collection")

    captured = {}
    monkeypatch.setattr(upload_module, "run_ingest", lambda config: captured.update(config))

    upload_module.main()

    assert captured["mode"] == "ingest"
    assert captured["pdf_path"] == "paper.pdf"
    assert captured["collection"] == "manual_collection"
