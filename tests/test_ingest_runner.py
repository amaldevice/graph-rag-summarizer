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
            self.collection_name = collection_name

        def prepare_ingest(self, ingest_mode, document_id, vector_size):
            self.ingest_mode = ingest_mode
            self.document_id = document_id
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


def test_run_ingest_stamps_document_identity_before_upload(monkeypatch, tmp_path):
    dummy_pdf = tmp_path / "paper.pdf"
    dummy_pdf.write_text("not a real pdf")

    loader_module = _types.ModuleType("preprocessing.docling_loader")
    embedder_module = _types.ModuleType("embedding.embedder")
    qdrant_module = _types.ModuleType("vectordb.qdrant_handler")
    captured = {}

    class FakeLoader:
        def process_pdf(self, pdf_path):
            return {"chunks": [{"chunk_id": 0, "text": "hello"}], "images": []}

    class FakeEmbedder:
        def embed_chunks(self, chunks):
            return [[0.1, 0.2] for _ in chunks]

    class FakeQdrantHandler:
        def __init__(self, collection_name="test"):
            captured["collection_name"] = collection_name

        def prepare_ingest(self, ingest_mode, document_id, vector_size):
            captured["prepare"] = (ingest_mode, document_id, vector_size)

        def upsert_chunks(self, chunks, vectors):
            captured["chunks"] = chunks
            captured["vectors"] = vectors

    loader_module.DoclingLoader = FakeLoader
    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module.QdrantHandler = FakeQdrantHandler
    monkeypatch.setitem(sys.modules, "preprocessing.docling_loader", loader_module)
    monkeypatch.setitem(sys.modules, "embedding.embedder", embedder_module)
    monkeypatch.setitem(sys.modules, "vectordb.qdrant_handler", qdrant_module)

    from launcher.runners import run_ingest

    run_ingest({
        "mode": "ingest",
        "profile": "local",
        "collection": "test_col",
        "pdf_path": str(dummy_pdf),
        "ingest_mode": "append",
        "document_id": "paper-a",
        "verbose": False,
    })

    assert captured["prepare"] == ("append", "paper-a", 2)
    assert captured["chunks"][0]["document_id"] == "paper-a"
    assert captured["chunks"][0]["chunk_uid"] == "paper-a:chunk:0"


def test_document_identity_stamping_preserves_parent_chunk_identity():
    from launcher.runners import _stamp_document_identity
    from vectordb.qdrant_handler import stable_point_id

    chunks = [{
        "chunk_id": 2,
        "hierarchy": {"parent_chunk_id": 1},
    }]

    stamped = _stamp_document_identity(chunks, "paper-a")

    assert stamped[0]["hierarchy"]["parent_chunk_uid"] == "paper-a:chunk:1"
    assert stamped[0]["hierarchy"]["parent_point_id"] == stable_point_id("paper-a", 1)


def test_on_demand_images_do_not_cross_document_boundaries(monkeypatch, tmp_path, capsys):
    from config import settings
    from launcher.runners import _maybe_render_images

    local_pdf = tmp_path / "paper-a.pdf"
    local_pdf.write_text("not a real pdf")
    loader_module = _types.ModuleType("preprocessing.docling_loader")

    class FakeLoader:
        def render_and_upload_pages_on_demand(self, pdf_path, target_pages):
            assert pdf_path == str(local_pdf)
            assert target_pages == [3]
            return [{"page": 3, "image_url": "https://example.test/paper-a-page-3.png"}]

        def build_page_image_map(self, uploaded_images):
            return {item["page"]: item["image_url"] for item in uploaded_images}

    loader_module.DoclingLoader = FakeLoader
    monkeypatch.setitem(sys.modules, "preprocessing.docling_loader", loader_module)
    monkeypatch.setattr(settings, "ENABLE_ON_DEMAND_PAGE_RENDER", True)

    chunks = [
        {"source": "paper-a.pdf", "document_id": "paper-a", "page_no": 3},
        {"source": "paper-b.pdf", "document_id": "paper-b", "page_no": 3},
    ]
    result = _maybe_render_images(chunks, str(local_pdf))

    assert result[0]["image_url"] == "https://example.test/paper-a-page-3.png"
    assert "image_url" not in result[1]
    assert "Mixed-document retrieval" in capsys.readouterr().out

    custom_id_chunks = [{
        "source": "paper-a.pdf",
        "document_id": "custom-paper-id",
        "page_no": 3,
    }]
    result = _maybe_render_images(custom_id_chunks, str(local_pdf))
    assert "image_url" not in result[0]
    assert "does not match the local PDF" in capsys.readouterr().out
