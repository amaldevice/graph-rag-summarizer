# ============================================================
# QUERY-ONLY RUNNER TESTS
# Proves Query-Only Run works without Groq-dependent imports
# and produces retrieval output.
# ============================================================

import importlib
import json
import sys
import types
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def test_query_only_does_not_import_groq(monkeypatch):
    """Query-Only Run must not trigger Groq or pipeline imports."""
    import builtins

    groq_imported = []
    real_import = builtins.__import__

    def tracking_import(name, *args, **kwargs):
        if "groq" in name.lower():
            groq_imported.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", tracking_import)

    embedder_module = types.ModuleType("embedding.embedder")
    qdrant_module = types.ModuleType("vectordb.qdrant_handler")

    class FakeEmbedder:
        def embed_text(self, text):
            return [0.1, 0.2]

    class FakeQdrantHandler:
        def __init__(self, collection_name="test"):
            pass

        def revalidate_query_authorization(self):
            pass

        def search_as_chunks(self, query_vector, limit):
            return [
                {"chunk_id": 1, "text": "chunk one", "page_no": 1, "score": 0.9, "rank": 1},
                {"chunk_id": 2, "text": "chunk two", "page_no": 2, "score": 0.8, "rank": 2},
            ]

    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module.QdrantHandler = FakeQdrantHandler

    monkeypatch.setitem(sys.modules, "embedding.embedder", embedder_module)
    monkeypatch.setitem(sys.modules, "vectordb.qdrant_handler", qdrant_module)

    from launcher.runners import run_query_only
    monkeypatch.setattr("launcher.runners._configure_query_denial", lambda *args: None)

    config = {
        "mode": "query-only",
        "profile": "local",
        "collection": "test_col",
        "query": "What is this?",
        "retrieval_limit": 5,
        "json_output": "",
    }

    run_query_only(config)

    assert not groq_imported, f"Groq was imported during Query-Only: {groq_imported}"


def test_query_only_produces_json_artifact(tmp_path, monkeypatch):
    """Query-Only Run should produce a valid JSON artifact."""
    embedder_module = types.ModuleType("embedding.embedder")
    qdrant_module = types.ModuleType("vectordb.qdrant_handler")

    class FakeEmbedder:
        def embed_text(self, text):
            return [0.1, 0.2]

    class FakeQdrantHandler:
        def __init__(self, collection_name="test"):
            pass

        def revalidate_query_authorization(self):
            pass

        def search_as_chunks(self, query_vector, limit):
            return [
                {"chunk_id": 1, "text": "hello world", "page_no": 1, "score": 0.95, "rank": 1},
            ]

    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module.QdrantHandler = FakeQdrantHandler

    monkeypatch.setitem(sys.modules, "embedding.embedder", embedder_module)
    monkeypatch.setitem(sys.modules, "vectordb.qdrant_handler", qdrant_module)

    from launcher.runners import run_query_only
    monkeypatch.setattr("launcher.runners._configure_query_denial", lambda *args: None)

    json_path = str(tmp_path / "query_results.json")
    config = {
        "mode": "query-only",
        "profile": "local",
        "collection": "test_col",
        "query": "test query",
        "retrieval_limit": 10,
        "json_output": json_path,
        "verbose": True,
    }

    run_query_only(config)

    assert Path(json_path).exists()
    with open(json_path) as f:
        artifact = json.load(f)
    assert artifact["mode"] == "query-only"
    assert artifact["query"] == "test query"
    assert artifact["chunk_count"] == 1
    assert len(artifact["chunks"]) == 1
    assert artifact["chunks"][0]["text"] == "hello world"


def test_query_only_handles_empty_results(monkeypatch):
    """Query-Only Run handles zero chunks gracefully."""
    embedder_module = types.ModuleType("embedding.embedder")
    qdrant_module = types.ModuleType("vectordb.qdrant_handler")

    class FakeEmbedder:
        def embed_text(self, text):
            return [0.1, 0.2]

    class FakeQdrantHandler:
        def __init__(self, collection_name="test"):
            pass

        def revalidate_query_authorization(self):
            pass

        def search_as_chunks(self, query_vector, limit):
            return []

    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module.QdrantHandler = FakeQdrantHandler

    monkeypatch.setitem(sys.modules, "embedding.embedder", embedder_module)
    monkeypatch.setitem(sys.modules, "vectordb.qdrant_handler", qdrant_module)

    from launcher.runners import run_query_only
    monkeypatch.setattr("launcher.runners._configure_query_denial", lambda *args: None)

    config = {
        "mode": "query-only",
        "profile": "local",
        "collection": "empty_col",
        "query": "nothing here",
        "retrieval_limit": 5,
        "json_output": "",
        "verbose": False,
    }

    run_query_only(config)


def test_query_only_prints_stage_progress(monkeypatch, capsys):
    embedder_module = types.ModuleType("embedding.embedder")
    qdrant_module = types.ModuleType("vectordb.qdrant_handler")

    class FakeEmbedder:
        def embed_text(self, text):
            return [0.1, 0.2]

    class FakeQdrantHandler:
        def __init__(self, collection_name="test"):
            pass

        def revalidate_query_authorization(self):
            pass

        def search_as_chunks(self, query_vector, limit):
            return [
                {"chunk_id": 1, "text": "hello world", "page_no": 1, "score": 0.95, "rank": 1},
            ]

    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module.QdrantHandler = FakeQdrantHandler

    monkeypatch.setitem(sys.modules, "embedding.embedder", embedder_module)
    monkeypatch.setitem(sys.modules, "vectordb.qdrant_handler", qdrant_module)

    from launcher.runners import run_query_only
    monkeypatch.setattr("launcher.runners._configure_query_denial", lambda *args: None)

    run_query_only(
        {
            "mode": "query-only",
            "profile": "local",
            "collection": "test_col",
            "query": "test query",
            "retrieval_limit": 10,
            "json_output": "",
            "verbose": False,
        }
    )

    output = capsys.readouterr().out
    assert "Stage 1/3" in output
    assert "Stage 2/3" in output
    assert "Stage 3/3" in output


def test_query_only_enforces_tombstone_preflight_when_graph_artifacts_are_disabled(monkeypatch):
    """The artifact flag cannot bypass persistent document denial."""
    embedder_module = types.ModuleType("embedding.embedder")
    qdrant_module = types.ModuleType("vectordb.qdrant_handler")
    configured = []

    class FakeEmbedder:
        def embed_text(self, text):
            del text
            return [0.1, 0.2]

    class FakeQdrantHandler:
        def __init__(self, collection_name="test"):
            del collection_name
            self.denied_document_ids = set()

        def set_denied_document_ids(self, document_ids):
            self.denied_document_ids = set(document_ids)

        def search_as_chunks(self, query_vector, limit):
            del query_vector, limit
            assert self.denied_document_ids == {"tombstoned-paper"}
            return [{"chunk_id": 1, "document_id": "active-paper", "text": "safe", "page_no": 1}]

        def revalidate_query_authorization(self):
            configured.append("revalidated")

    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module.QdrantHandler = FakeQdrantHandler
    monkeypatch.setitem(sys.modules, "embedding.embedder", embedder_module)
    monkeypatch.setitem(sys.modules, "vectordb.qdrant_handler", qdrant_module)

    from launcher.runners import run_query_only

    def configure_query_safety(qdrant, collection, object_store=None):
        del collection, object_store
        configured.append("configured")
        qdrant.set_denied_document_ids(["tombstoned-paper"])

    monkeypatch.setattr("launcher.runners._configure_query_denial", configure_query_safety)

    run_query_only({
        "mode": "query-only",
        "profile": "local",
        "collection": "test_col",
        "query": "test query",
        "retrieval_limit": 5,
        "json_output": "",
        "enable_graph_artifact": False,
    })

    assert configured == ["configured", "revalidated"]
