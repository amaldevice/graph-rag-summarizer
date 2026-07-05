# ============================================================
# INGEST RUNNER TESTS
# Ingest safety guards, PDF validation, collection suggestion.
# ============================================================

import sys
import types as _types
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

from launcher.contract import suggest_collection_from_pdf, check_availability


def test_ingest_suggests_collection_from_pdf_name():
    assert suggest_collection_from_pdf("My Research Paper.pdf") == "my_research_paper"
    assert suggest_collection_from_pdf("/tmp/doc-2024.pdf") == "doc-2024"
    assert suggest_collection_from_pdf("file with spaces.pdf") == "file_with_spaces"


def test_ingest_always_available_regardless_of_groq(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert check_availability("ingest", "local") == []
    assert check_availability("ingest", "cloud") == []


def test_run_ingest_fails_on_missing_pdf(monkeypatch):
    from launcher.runners import run_ingest

    config = {
        "mode": "ingest",
        "profile": "local",
        "collection": "test_col",
        "pdf_path": "/nonexistent/file.pdf",
        "retrieval_limit": 10,
        "json_output": "",
        "verbose": False,
    }

    with pytest.raises(SystemExit, match="PDF file not found"):
        run_ingest(config)


def test_run_ingest_fails_on_empty_chunks(monkeypatch, tmp_path):
    dummy_pdf = tmp_path / "empty.pdf"
    dummy_pdf.write_text("not a real pdf")

    loader_module = _types.ModuleType("preprocessing.docling_loader")
    embedder_module = _types.ModuleType("embedding.embedder")
    qdrant_module = _types.ModuleType("vectordb.qdrant_handler")

    class FakeLoader:
        def process_pdf(self, pdf_path):
            return {"chunks": [], "doc_result": None, "images": [], "page_image_map": {}}

    class FakeEmbedder:
        def embed_chunks(self, chunks):
            return []

    loader_module.DoclingLoader = FakeLoader
    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module.QdrantHandler = lambda **kw: None

    monkeypatch.setitem(sys.modules, "preprocessing.docling_loader", loader_module)
    monkeypatch.setitem(sys.modules, "embedding.embedder", embedder_module)
    monkeypatch.setitem(sys.modules, "vectordb.qdrant_handler", qdrant_module)

    from launcher.runners import run_ingest

    config = {
        "mode": "ingest",
        "profile": "local",
        "collection": "test_col",
        "pdf_path": str(dummy_pdf),
        "retrieval_limit": 10,
        "json_output": "",
        "verbose": False,
    }

    with pytest.raises(SystemExit, match="No chunks extracted"):
        run_ingest(config)


def test_run_ingest_prints_stage_progress(monkeypatch, tmp_path, capsys):
    dummy_pdf = tmp_path / "paper.pdf"
    dummy_pdf.write_text("not a real pdf")

    loader_module = _types.ModuleType("preprocessing.docling_loader")
    embedder_module = _types.ModuleType("embedding.embedder")
    qdrant_module = _types.ModuleType("vectordb.qdrant_handler")

    class FakeLoader:
        def process_pdf(self, pdf_path):
            return {
                "chunks": [{"chunk_id": 1, "text": "hello"}],
                "doc_result": None,
                "images": [],
                "page_image_map": {},
            }

    class FakeEmbedder:
        def embed_chunks(self, chunks):
            return [[0.1, 0.2] for _ in chunks]

    class FakeQdrantHandler:
        def __init__(self, collection_name="test"):
            pass

        def create_collection_if_not_exists(self, vector_size):
            self.vector_size = vector_size

        def upsert_chunks(self, chunks, vectors):
            self.count = len(chunks)

    loader_module.DoclingLoader = FakeLoader
    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module.QdrantHandler = FakeQdrantHandler

    monkeypatch.setitem(sys.modules, "preprocessing.docling_loader", loader_module)
    monkeypatch.setitem(sys.modules, "embedding.embedder", embedder_module)
    monkeypatch.setitem(sys.modules, "vectordb.qdrant_handler", qdrant_module)

    from launcher.runners import run_ingest

    run_ingest(
        {
            "mode": "ingest",
            "profile": "local",
            "collection": "test_col",
            "pdf_path": str(dummy_pdf),
            "retrieval_limit": 10,
            "json_output": "",
            "verbose": False,
        }
    )

    output = capsys.readouterr().out
    assert "Stage 1/4" in output
    assert "Stage 2/4" in output
    assert "Stage 3/4" in output
    assert "Stage 4/4" in output
