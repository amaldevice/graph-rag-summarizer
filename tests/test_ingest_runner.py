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


def test_query_authorization_fails_closed_without_manifest_entries(monkeypatch):
    from graph import persistent
    from launcher.runners import _configure_query_denial

    snapshot = _types.SimpleNamespace(manifest={
        "documents": {},
        "tombstone_set_digest": "empty-proof",
        "pending_tombstone_set_digest": None,
        "collection_operation_id": None,
    })

    class FakeManifests:
        def read_snapshot(self):
            return snapshot

        def tombstone_controls(self, manifest):
            assert manifest is snapshot.manifest
            return []

        def revalidate(self, candidate):
            return candidate is snapshot

    class FakeQdrant:
        def verify_tombstone_control_points(self, controls, expected_digest):
            assert controls == []
            assert expected_digest == "empty-proof"

        def set_denied_document_ids(self, document_ids):
            self.denied = document_ids

        def set_query_authorization(self, manifests, candidate):
            self.authorization = (manifests, candidate)

        def set_active_vector_generations(self, generations):
            self.active_vectors = generations

        def set_active_graph_selectors(self, selectors):
            self.active_graphs = selectors

    manifests = FakeManifests()
    monkeypatch.setattr(persistent, "default_graph_services", lambda collection, object_store: (manifests, None))
    qdrant = FakeQdrant()

    _configure_query_denial(qdrant, "papers")

    assert qdrant.denied == []
    assert qdrant.active_vectors == {}
    assert qdrant.active_graphs == {}


def test_query_authorization_limits_graph_to_available_entries_and_keeps_vector_fallback(monkeypatch):
    from graph import persistent
    from launcher.runners import _configure_query_denial

    documents = {
        "available": {
            "status": "available",
            "document_generation": 1,
            "document_attempt_id": "available-attempt",
            "vector_ready": True,
        },
        "partial": {
            "status": "partial",
            "document_generation": 2,
            "document_attempt_id": "partial-attempt",
            "vector_ready": True,
        },
        "pending": {
            "status": "pending",
            "document_generation": 3,
            "document_attempt_id": "pending-attempt",
            "previous_pointer": {"document_generation": 2},
            "vector_ready": False,
        },
        "stale": {
            "status": "stale",
            "document_generation": 4,
            "document_attempt_id": "stale-attempt",
            "vector_ready": True,
        },
        "unavailable": {
            "status": "unavailable",
            "document_generation": 5,
            "document_attempt_id": "unavailable-attempt",
            "vector_ready": True,
        },
        "not-ready": {
            "status": "unavailable",
            "document_generation": 6,
            "document_attempt_id": "not-ready-attempt",
            "vector_ready": False,
        },
        "tombstoned": {
            "status": "tombstoned",
            "document_generation": 7,
            "document_attempt_id": "tombstone-attempt",
            "vector_ready": True,
        },
    }
    snapshot = _types.SimpleNamespace(manifest={
        "documents": documents,
        "tombstone_set_digest": "proof",
        "pending_tombstone_set_digest": None,
        "collection_operation_id": None,
    })

    class FakeManifests:
        def read_snapshot(self):
            return snapshot

        def tombstone_controls(self, manifest):
            return []

        def revalidate(self, candidate):
            return candidate is snapshot

    class FakeQdrant:
        def verify_tombstone_control_points(self, controls, expected_digest):
            assert controls == []
            assert expected_digest == "proof"

        def set_denied_document_ids(self, document_ids):
            self.denied = document_ids

        def set_query_authorization(self, manifests, candidate):
            del manifests, candidate

        def set_active_vector_generations(self, generations):
            self.active_vectors = generations

        def set_active_graph_selectors(self, selectors):
            self.active_graphs = selectors

    manifests = FakeManifests()
    monkeypatch.setattr(persistent, "default_graph_services", lambda collection, object_store: (manifests, None))
    qdrant = FakeQdrant()

    _configure_query_denial(qdrant, "papers")

    assert qdrant.denied == ["tombstoned"]
    assert qdrant.active_vectors == {
        "available": 1,
        "partial": 2,
        "pending": 2,
        "stale": 4,
        "unavailable": 5,
    }
    assert qdrant.active_graphs == {
        "available": {
            "document_generation": 1,
            "document_attempt_id": "available-attempt",
        },
    }


def test_graph_claim_is_attached_before_normal_ingest_qdrant_mutation(monkeypatch, tmp_path):
    from graph import persistent
    from launcher.runners import run_ingest

    dummy_pdf = tmp_path / "paper.pdf"
    dummy_pdf.write_text("not a real pdf")
    events = []
    claim = {"pending_attempt_id": "attempt-1"}

    class FakeManifests:
        def mark_vectors_ready(self, candidate):
            assert candidate is claim
            events.append("mark-vectors-ready")

    class FakePipeline:
        def __init__(self, collection, object_store=None):
            assert collection == "papers"
            assert object_store is None
            self.manifests = FakeManifests()

        def reserve(self, chunks, document_id, mode):
            assert document_id == "paper-a"
            assert mode == "append"
            events.append("reserve")
            return claim

        def build_and_publish(self, chunks, vectors, document_id, **kwargs):
            assert len(chunks) == len(vectors) == 1
            assert document_id == "paper-a"
            assert kwargs["claim"] is claim
            return {"status": "available"}

    class FakeLoader:
        def process_pdf(self, pdf_path):
            assert pdf_path == str(dummy_pdf)
            return {"chunks": [{"chunk_id": 1, "text": "hello"}]}

    class FakeEmbedder:
        def embed_chunks(self, chunks):
            assert chunks[0]["document_id"] == "paper-a"
            return [[0.1, 0.2]]

    class FakeQdrant:
        def __init__(self, collection_name):
            assert collection_name == "papers"

        def set_graph_claim(self, manifests, candidate):
            assert isinstance(manifests, FakeManifests)
            assert candidate is claim
            events.append("set-graph-claim")

        def prepare_ingest(self, **kwargs):
            assert kwargs["claim"] is claim
            events.append("prepare-ingest")

        def upsert_chunks(self, chunks, vectors):
            assert len(chunks) == len(vectors) == 1
            events.append("upsert")
            return ["new-point"]

        def write_document_control_point(self, candidate, vector_size):
            assert candidate is claim
            assert vector_size == 2
            events.append("write-document-control")
            return "document-control"

        def verify_document_control_point(self, control_id):
            assert control_id == "document-control"
            events.append("verify-document-control")

    loader_module = _types.ModuleType("preprocessing.docling_loader")
    loader_module.DoclingLoader = FakeLoader
    embedder_module = _types.ModuleType("embedding.embedder")
    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module = _types.ModuleType("vectordb.qdrant_handler")
    qdrant_module.QdrantHandler = FakeQdrant
    monkeypatch.setitem(sys.modules, "preprocessing.docling_loader", loader_module)
    monkeypatch.setitem(sys.modules, "embedding.embedder", embedder_module)
    monkeypatch.setitem(sys.modules, "vectordb.qdrant_handler", qdrant_module)
    monkeypatch.setattr(persistent, "PersistentGraphPipeline", FakePipeline)

    run_ingest({
        "collection": "papers",
        "pdf_path": str(dummy_pdf),
        "document_id": "paper-a",
        "ingest_mode": "append",
        "enable_graph_artifact": True,
        "graph_relation_provider": object(),
        "artifact_dir": str(tmp_path),
    })

    assert events.index("set-graph-claim") < events.index("prepare-ingest")


def test_legacy_vector_ingest_pins_mode_without_graph_lifecycle(monkeypatch, tmp_path):
    from graph import persistent
    from launcher.runners import run_ingest

    dummy_pdf = tmp_path / "paper.pdf"
    dummy_pdf.write_text("not a real pdf")
    events = []

    class FakeLoader:
        def process_pdf(self, pdf_path):
            assert pdf_path == str(dummy_pdf)
            return {"chunks": [{"chunk_id": 1, "text": "legacy"}]}

    class FakeEmbedder:
        def embed_chunks(self, chunks):
            assert chunks[0]["document_id"] == "paper-a"
            return [[0.1, 0.2]]

    class FakeQdrant:
        def __init__(self, collection_name):
            assert collection_name == "legacy"

        def prepare_ingest(self, **kwargs):
            assert "claim" not in kwargs
            events.append("prepare")

        def upsert_chunks(self, chunks, vectors):
            assert len(chunks) == len(vectors) == 1
            events.append("upsert")
            return ["point"]

    class FailPipeline:
        def __init__(self, *args, **kwargs):
            raise AssertionError("legacy mode must not create a persistent graph pipeline")

    loader_module = _types.ModuleType("preprocessing.docling_loader")
    loader_module.DoclingLoader = FakeLoader
    embedder_module = _types.ModuleType("embedding.embedder")
    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module = _types.ModuleType("vectordb.qdrant_handler")
    qdrant_module.QdrantHandler = FakeQdrant
    monkeypatch.setitem(sys.modules, "preprocessing.docling_loader", loader_module)
    monkeypatch.setitem(sys.modules, "embedding.embedder", embedder_module)
    monkeypatch.setitem(sys.modules, "vectordb.qdrant_handler", qdrant_module)
    monkeypatch.setattr(persistent, "PersistentGraphPipeline", FailPipeline)
    monkeypatch.setattr(
        "launcher.runners._bind_ingest_collection_mode",
        lambda collection, mode, **kwargs: events.append(("bind", collection, mode)),
    )

    run_ingest({
        "collection": "legacy",
        "collection_mode": "legacy-vector",
        "pdf_path": str(dummy_pdf),
        "document_id": "paper-a",
        "ingest_mode": "append",
        "enable_graph_artifact": True,
    })

    assert events == [("bind", "legacy", "legacy-vector"), "prepare", "upsert"]


def test_document_safe_ingest_does_not_pin_a_legacy_collection(monkeypatch, tmp_path):
    from graph import persistent
    from launcher.runners import run_ingest

    dummy_pdf = tmp_path / "paper.pdf"
    dummy_pdf.write_text("not a real pdf")

    class FakeLoader:
        def process_pdf(self, pdf_path):
            assert pdf_path == str(dummy_pdf)
            return {"chunks": [{"chunk_id": 1, "text": "legacy"}]}

    class FakeEmbedder:
        def embed_chunks(self, chunks):
            assert len(chunks) == 1
            return [[0.1, 0.2]]

    class FakeQdrant:
        def __init__(self, collection_name):
            assert collection_name == "legacy"

        def collection_exists(self):
            return True

        def has_legacy_points(self):
            return True

    class FailPipeline:
        def __init__(self, *args, **kwargs):
            raise AssertionError("legacy preflight must run before graph reservation")

    loader_module = _types.ModuleType("preprocessing.docling_loader")
    loader_module.DoclingLoader = FakeLoader
    embedder_module = _types.ModuleType("embedding.embedder")
    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module = _types.ModuleType("vectordb.qdrant_handler")
    qdrant_module.QdrantHandler = FakeQdrant
    monkeypatch.setitem(sys.modules, "preprocessing.docling_loader", loader_module)
    monkeypatch.setitem(sys.modules, "embedding.embedder", embedder_module)
    monkeypatch.setitem(sys.modules, "vectordb.qdrant_handler", qdrant_module)
    monkeypatch.setattr(persistent, "PersistentGraphPipeline", FailPipeline)
    monkeypatch.setattr(
        "launcher.runners._bind_ingest_collection_mode",
        lambda *args, **kwargs: pytest.fail("legacy preflight must run before mode pinning"),
    )

    with pytest.raises(SystemExit, match="contains legacy points.*legacy-vector"):
        run_ingest({
            "collection": "legacy",
            "collection_mode": "document-safe",
            "pdf_path": str(dummy_pdf),
            "document_id": "paper-a",
            "ingest_mode": "append",
            "enable_graph_artifact": True,
        })


@pytest.mark.parametrize(
    ("artifact_fields", "artifact_error", "error_match"),
    [
        (
            {
                "active_artifact_key": "graphs/papers/paper-a/v1/graph.json.gz",
                "artifact_digest": "artifact-digest",
                "backend": {"kind": "memory", "namespace": "test"},
                "document_generation": 1,
            },
            None,
            None,
        ),
        ({}, None, "incomplete artifact tuple"),
        (
            {
                "active_artifact_key": "graphs/papers/paper-a/v1/graph.json.gz",
                "artifact_digest": "artifact-digest",
                "backend": {"kind": "memory", "namespace": "test"},
                "document_generation": 1,
            },
            ValueError("corrupt graph artifact"),
            "artifact validation failed",
        ),
    ],
    ids=["valid-artifact", "missing-artifact", "invalid-artifact"],
)
def test_completed_replace_collection_resume_validates_artifact_before_release(
    monkeypatch,
    tmp_path,
    artifact_fields,
    artifact_error,
    error_match,
):
    from graph import persistent
    from launcher.runners import run_ingest

    dummy_pdf = tmp_path / "paper.pdf"
    dummy_pdf.write_text("not a real pdf")
    events = []
    entry = {
        "status": "available",
        "source_fingerprint": "source-fingerprint",
        "document_attempt_id": "document-attempt",
        "collection_fence_token": 7,
        "collection_attempt_id": "replace-1-attempt",
    }
    entry.update(artifact_fields)
    manifest = {
        "collection_operation_id": "replace-1",
        "collection_fence_token": 7,
        "collection_attempt_id": "replace-1-attempt",
        "pending_tombstone_set_digest": None,
        "documents": {
            "paper-a": entry,
        },
    }

    class FakeManifests:
        def read_snapshot(self):
            return _types.SimpleNamespace(manifest=manifest)

        def tombstone_documents(self, retained_documents, operation_id):
            assert retained_documents == {"paper-a": "source-fingerprint"}
            assert operation_id == "replace-1"
            events.append("tombstone-documents")
            return manifest

        def get(self, document_id):
            return manifest["documents"].get(document_id)

        def release_collection_fence(self, operation_id, fence_token):
            events.append(("release-collection-fence", operation_id, fence_token))

    class FakePipeline:
        def __init__(self, collection, object_store=None):
            assert collection == "papers"
            self.manifests = FakeManifests()
            self.artifacts = FakeArtifacts()

        def reserve(self, *args, **kwargs):
            raise AssertionError("completed resume must not reserve another document claim")

    class FakeArtifacts:
        def read(self, key, digest, backend, generation, source_fingerprint):
            events.append(("artifact-read", key, digest, backend, generation, source_fingerprint))
            if artifact_error:
                raise artifact_error
            return b"{}"

    class FakeLoader:
        def process_pdf(self, pdf_path):
            assert pdf_path == str(dummy_pdf)
            return {"chunks": [{"chunk_id": 1, "text": "hello"}]}

    class FakeEmbedder:
        def embed_chunks(self, chunks):
            assert chunks[0]["document_id"] == "paper-a"
            return [[0.1, 0.2]]

    class FakeQdrant:
        def __init__(self, collection_name):
            assert collection_name == "papers"

        def set_collection_claim(self, manifests, operation_id, fence_token, attempt_id):
            assert isinstance(manifests, FakeManifests)
            assert (operation_id, fence_token, attempt_id) == ("replace-1", 7, "replace-1-attempt")
            events.append("set-collection-claim")

        def verify_collection_tombstone_proof(self, manifests):
            assert isinstance(manifests, FakeManifests)
            events.append("verify-collection-proof")

        def prepare_ingest(self, **kwargs):
            raise AssertionError("completed resume must not mutate Qdrant")

    loader_module = _types.ModuleType("preprocessing.docling_loader")
    loader_module.DoclingLoader = FakeLoader
    embedder_module = _types.ModuleType("embedding.embedder")
    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module = _types.ModuleType("vectordb.qdrant_handler")
    qdrant_module.QdrantHandler = FakeQdrant
    monkeypatch.setitem(sys.modules, "preprocessing.docling_loader", loader_module)
    monkeypatch.setitem(sys.modules, "embedding.embedder", embedder_module)
    monkeypatch.setitem(sys.modules, "vectordb.qdrant_handler", qdrant_module)
    monkeypatch.setattr(persistent, "PersistentGraphPipeline", FakePipeline)
    monkeypatch.setattr(persistent, "source_fingerprint", lambda chunks, document_id: "source-fingerprint")

    config = {
        "collection": "papers",
        "pdf_path": str(dummy_pdf),
        "document_id": "paper-a",
        "ingest_mode": "replace-collection",
        "enable_graph_artifact": True,
    }
    if error_match:
        with pytest.raises(RuntimeError, match=error_match):
            run_ingest(config)
        assert "verify-collection-proof" not in events
        assert not any(event[0] == "release-collection-fence" for event in events if isinstance(event, tuple))
        return

    run_ingest(config)

    assert events == [
        "tombstone-documents",
        "set-collection-claim",
        (
            "artifact-read",
            "graphs/papers/paper-a/v1/graph.json.gz",
            "artifact-digest",
            {"kind": "memory", "namespace": "test"},
            1,
            "source-fingerprint",
        ),
        "verify-collection-proof",
        ("release-collection-fence", "replace-1", 7),
    ]
