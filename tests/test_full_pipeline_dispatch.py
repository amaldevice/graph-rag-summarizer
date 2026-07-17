# ============================================================
# FULL-PIPELINE DISPATCH TESTS
# Availability gating, mode dispatch, and config forwarding.
# ============================================================

import sys
import types
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

from launcher.contract import check_availability


def test_full_pipeline_blocked_without_groq(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    missing = check_availability("full-pipeline", "local")
    assert len(missing) == 1
    assert "At least one configured LLM provider" in missing[0]


def test_full_pipeline_blocked_cloud_without_qdrant_and_groq(monkeypatch):
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    missing = check_availability("full-pipeline", "cloud")
    assert len(missing) >= 2


def test_full_pipeline_available_with_groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    assert check_availability("full-pipeline", "local") == []


def test_full_pipeline_available_with_gemini_only(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert check_availability("full-pipeline", "local") == []


def test_full_pipeline_requires_preferred_provider_when_fallback_disabled(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("LLM_ENABLE_FALLBACK", "false")

    missing = check_availability("full-pipeline", "local")

    assert len(missing) == 1
    assert "groq is required for Full-Pipeline Run when fallback is disabled" in missing[0]


def test_full_pipeline_dispatches_to_run_full_pipeline(monkeypatch):
    from launcher.runners import run_full_pipeline

    called_with = {}
    original_run = run_full_pipeline

    def capturing_run(config):
        called_with.update(config)

    monkeypatch.setattr("launcher.runners.run_full_pipeline", capturing_run)

    from launcher.runners import run_full_pipeline as dispatch_target

    config = {
        "mode": "full-pipeline",
        "profile": "local",
        "collection": "my_col",
        "query": "what is X",
        "retrieval_limit": 15,
        "pdf_path": "test.pdf",
        "json_output": "out.json",
    }

    dispatch_target(config)

    assert called_with["collection"] == "my_col"
    assert called_with["query"] == "what is X"
    assert called_with["retrieval_limit"] == 15


def test_full_pipeline_stops_before_graph_analysis_when_retrieval_is_empty(monkeypatch, tmp_path):
    embedder_module = types.ModuleType("embedding.embedder")
    qdrant_module = types.ModuleType("vectordb.qdrant_handler")

    class FakeEmbedder:
        def embed_text(self, text):
            assert text == "question"
            return [0.1, 0.2]

    class FakeQdrant:
        def __init__(self, collection_name):
            assert collection_name == "empty"

        def search_as_chunks(self, query_vector, limit):
            assert query_vector == [0.1, 0.2]
            assert limit == 2
            return []

        def revalidate_query_authorization(self):
            pass

    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module.QdrantHandler = FakeQdrant
    monkeypatch.setitem(sys.modules, "embedding.embedder", embedder_module)
    monkeypatch.setitem(sys.modules, "vectordb.qdrant_handler", qdrant_module)
    monkeypatch.setattr("launcher.runners._configure_query_denial", lambda *args: None)

    from launcher.runners import run_full_pipeline

    with pytest.raises(RuntimeError, match="no chunks retrieved.*document-safe mode"):
        run_full_pipeline({
            "mode": "full-pipeline",
            "profile": "local",
            "collection": "empty",
            "query": "question",
            "retrieval_limit": 2,
            "artifact_dir": str(tmp_path),
            "enable_graph_artifact": False,
        })


def test_full_pipeline_legacy_vector_uses_compatibility_path(monkeypatch, tmp_path):
    embedder_module = types.ModuleType("embedding.embedder")
    qdrant_module = types.ModuleType("vectordb.qdrant_handler")
    events = []

    class FakeEmbedder:
        def embed_text(self, text):
            assert text == "question"
            return [0.1, 0.2]

    class FakeQdrant:
        def __init__(self, collection_name):
            assert collection_name == "legacy"

        def search_as_chunks(self, query_vector, limit):
            assert query_vector == [0.1, 0.2]
            assert limit == 2
            events.append("search")
            return [{"chunk_id": 1, "text": "legacy result"}]

        def revalidate_query_authorization(self):
            events.append("revalidate")

    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module.QdrantHandler = FakeQdrant
    monkeypatch.setitem(sys.modules, "embedding.embedder", embedder_module)
    monkeypatch.setitem(sys.modules, "vectordb.qdrant_handler", qdrant_module)
    monkeypatch.setattr(
        "launcher.runners._validate_legacy_collection_mode",
        lambda *args: events.append("legacy-mode-validated"),
    )
    monkeypatch.setattr(
        "launcher.runners._configure_query_denial",
        lambda *args: (_ for _ in ()).throw(AssertionError("safe authorization must not run")),
    )
    monkeypatch.setattr(
        "launcher.runners._persistent_graph_view",
        lambda *args: (_ for _ in ()).throw(AssertionError("persistent graph must not run")),
    )
    monkeypatch.setattr(
        "launcher.runners._compatibility_or_vector_view",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("compatibility path reached")),
    )

    from launcher.runners import run_full_pipeline

    with pytest.raises(RuntimeError, match="compatibility path reached"):
        run_full_pipeline({
            "mode": "full-pipeline",
            "profile": "local",
            "collection": "legacy",
            "collection_mode": "legacy-vector",
            "query": "question",
            "retrieval_limit": 2,
            "artifact_dir": str(tmp_path),
            "enable_graph_artifact": True,
        })

    assert events == ["legacy-mode-validated", "search", "revalidate", "revalidate"]
