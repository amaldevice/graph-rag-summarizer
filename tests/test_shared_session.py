# ============================================================
# SHARED SESSION TESTS
# Proves summarizer + reducer share one provider session
# and sticky failover carries across stages.
# ============================================================

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

from config import settings
from summarizer.provider_router import ProviderRouter, create_session
from summarizer.llm_summarizer import LLMSummarizer
from summarizer.hierarchical_reducer import HierarchicalReducer


def test_summarizer_and_reducer_share_same_session(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    session = create_session(preferred_provider="groq", fallback_chain=["groq"])
    summarizer = LLMSummarizer(session=session)
    reducer = HierarchicalReducer(session=session)

    assert summarizer.session is reducer.session
    assert summarizer.session is session


def test_sticky_failover_carries_from_summarizer_to_reducer(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    session = create_session(
        preferred_provider="groq",
        fallback_chain=["groq", "gemini"],
        enable_fallback=True,
    )

    call_log = []

    def fake_call_with_retry(provider, system_prompt, user_prompt):
        call_log.append(provider)
        if provider == "groq":
            raise RuntimeError("rate limited")
        return f"{provider} result"

    monkeypatch.setattr(session, "_call_with_retry", fake_call_with_retry)

    summarizer = LLMSummarizer(session=session)
    reducer = HierarchicalReducer(session=session)

    summaries = summarizer.summarize_communities([
        {"community_id": 0, "prompt": "summarize", "chunk_ids": [1], "num_chunks": 1},
    ])
    assert summaries[0]["summary"] == "gemini result"

    result = reducer.reduce_summaries(summaries, query="test")
    assert result["final_summary"] == "gemini result"

    assert call_log == ["groq", "gemini", "gemini"]
    assert session.active_provider == "gemini"


def test_groq_only_backward_compatibility(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    session = create_session(preferred_provider="groq", fallback_chain=["groq"])

    def fake_call(provider, system_prompt, user_prompt):
        return "groq summary"

    monkeypatch.setattr(session, "_call_provider", fake_call)

    summarizer = LLMSummarizer(session=session)
    reducer = HierarchicalReducer(session=session)

    summaries = summarizer.summarize_communities([
        {"community_id": 0, "prompt": "summarize", "chunk_ids": [1], "num_chunks": 1},
    ])
    assert summaries[0]["summary"] == "groq summary"

    result = reducer.reduce_summaries(summaries, query="test")
    assert result["final_summary"] == "groq summary"
    assert session.active_provider == "groq"


def test_summarizer_produces_correct_output_format(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    session = create_session(preferred_provider="groq", fallback_chain=["groq"])

    def fake_call(provider, system_prompt, user_prompt):
        return "community summary text"

    monkeypatch.setattr(session, "_call_provider", fake_call)

    summarizer = LLMSummarizer(session=session)
    result = summarizer.summarize_communities([
        {"community_id": 5, "prompt": "prompt", "chunk_ids": [10, 11], "num_chunks": 2},
    ])

    assert len(result) == 1
    assert result[0]["community_id"] == 5
    assert result[0]["num_chunks"] == 2
    assert result[0]["chunk_ids"] == [10, 11]
    assert result[0]["summary"] == "community summary text"


def test_reducer_produces_correct_output_format(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    session = create_session(preferred_provider="groq", fallback_chain=["groq"])

    def fake_call(provider, system_prompt, user_prompt):
        return "final summary text"

    monkeypatch.setattr(session, "_call_provider", fake_call)

    reducer = HierarchicalReducer(session=session)
    result = reducer.reduce_summaries(
        [{"community_id": 0, "summary": "s1", "chunk_ids": [1]}],
        query="What is X?",
        style="concise",
    )

    assert result["query"] == "What is X?"
    assert result["num_communities"] == 1
    assert result["final_summary"] == "final summary text"
    assert result["community_ids"] == [0]


def test_reducer_build_reduce_prompt_includes_all_summaries(monkeypatch):
    session = create_session()
    reducer = HierarchicalReducer(session=session)

    prompt = reducer.build_reduce_prompt(
        [
            {"community_id": 1, "summary": "summary one", "chunk_ids": [1, 2]},
            {"community_id": 2, "summary": "summary two", "chunk_ids": [3, 4]},
        ],
        query="What is the main idea?",
        style="concise",
    )

    assert "summary one" in prompt
    assert "summary two" in prompt
    assert "What is the main idea?" in prompt
    assert "Community 1" in prompt
    assert "Community 2" in prompt
