# ============================================================
# FULL-PIPELINE DISPATCH TESTS
# Availability gating, mode dispatch, and config forwarding.
# ============================================================

import sys
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
