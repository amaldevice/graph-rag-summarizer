from pathlib import Path
import sys

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from summarizer.pruner import SummaryPruner
from summarizer.prompt_builder import PromptBuilder
from summarizer.llm_summarizer import LLMSummarizer


def _ranked(rows):
    return pd.DataFrame(rows)


def test_allocator_respects_total_and_community_character_caps_with_reasons():
    ranked = _ranked([
        {"node": "chunk_0", "type": "chunk", "community": 0, "rank": 1, "composite_score": 0.9, "text_preview": "a"},
        {"node": "chunk_1", "type": "chunk", "community": 0, "rank": 2, "composite_score": 0.8, "text_preview": "b"},
        {"node": "chunk_2", "type": "chunk", "community": 1, "rank": 3, "composite_score": 0.7, "text_preview": "c"},
        {"node": "chunk_3", "type": "chunk", "community": 2, "rank": 4, "composite_score": 0.1, "text_preview": "d"},
    ])
    chunks = [
        {"chunk_id": 0, "text": "A" * 24, "score": 0.95, "hierarchy": {"section_id": "a"}},
        {"chunk_id": 1, "text": "B" * 24, "score": 0.9, "hierarchy": {"section_id": "b"}},
        {"chunk_id": 2, "text": "C" * 24, "score": 0.8, "hierarchy": {"section_id": "c"}},
        {"chunk_id": 3, "text": "D" * 24, "score": 0.0, "hierarchy": {"section_id": "d"}},
    ]

    result = SummaryPruner(
        context_char_budget=200,
        min_community_chars=40,
        max_community_chars=100,
        max_community_share=0.6,
    ).select_top_chunks(ranked, chunks)

    allocation = result["context_allocation"]
    assert allocation["consumed_characters"] <= allocation["character_budget"] == 200
    by_community = {item["community_id"]: item for item in allocation["communities"]}
    assert by_community[0]["allocated_characters"] <= 100
    assert by_community[1]["allocated_characters"] <= 100
    assert by_community[2]["reason"] == "below_relevance_floor"
    assert all(item["selection_reason"] for item in allocation["selected_chunks"])
    assert any(item["reason"] == "below_relevance_floor" for item in allocation["rejected_chunks"])


def test_allocator_uses_novelty_and_not_legacy_top_k_limit():
    ranked = _ranked([
        {"node": "chunk_0", "type": "chunk", "community": 0, "rank": 1, "composite_score": 0.95, "text_preview": "same"},
        {"node": "chunk_1", "type": "chunk", "community": 0, "rank": 2, "composite_score": 0.9, "text_preview": "same"},
        {"node": "chunk_2", "type": "chunk", "community": 0, "rank": 3, "composite_score": 0.7, "text_preview": "different"},
    ])
    chunks = [
        {"chunk_id": 0, "text": "alpha beta gamma delta epsilon zeta eta theta", "score": 0.95},
        {"chunk_id": 1, "text": "alpha beta gamma delta epsilon zeta eta theta", "score": 0.9},
        {"chunk_id": 2, "text": "different evidence adds a separate finding", "score": 0.7},
    ]

    result = SummaryPruner(
        top_k_per_community=1,
        context_char_budget=1_000,
        min_community_chars=200,
        max_community_chars=900,
        min_marginal_gain=0.2,
    ).select_top_chunks(ranked, chunks)

    selected_ids = [item["chunk_id"] for item in result["global_top_chunks"]]
    assert 0 in selected_ids and 2 in selected_ids
    assert 1 not in selected_ids
    rejected = {item["chunk_id"]: item["reason"] for item in result["context_allocation"]["rejected_chunks"]}
    assert rejected[1] == "redundant_evidence"


def test_allocator_preserves_query_protected_chunk_and_degrades_without_path_signal():
    ranked = _ranked([
        {"node": "chunk_0", "type": "chunk", "community": 0, "rank": 1, "composite_score": 0.9, "text_preview": "strong"},
        {"node": "chunk_1", "type": "chunk", "community": 1, "rank": 2, "composite_score": 0.0, "text_preview": "protected"},
    ])
    chunks = [
        {"chunk_id": 0, "text": "strong evidence", "score": 0.9},
        {"chunk_id": 1, "text": "protected evidence", "score": 0.0, "query_protected": True},
    ]

    result = SummaryPruner(
        context_char_budget=1_000,
        min_community_chars=100,
        max_community_chars=500,
    ).select_top_chunks(ranked, chunks)

    allocation = result["context_allocation"]
    assert allocation["path_signal_status"] == "unavailable"
    protected = next(item for item in allocation["selected_chunks"] if item["chunk_id"] == 1)
    assert protected["selection_reason"] == "query_protected"


def test_query_protected_chunk_reserves_budget_beyond_community_cap():
    ranked = _ranked([
        {"node": "chunk_0", "type": "chunk", "community": 0, "rank": 1, "composite_score": 0.9, "text_preview": "strong"},
        {"node": "chunk_1", "type": "chunk", "community": 1, "rank": 2, "composite_score": 0.0, "text_preview": "protected"},
    ])
    chunks = [
        {"chunk_id": 0, "text": "strong evidence", "score": 0.9},
        {"chunk_id": 1, "text": "P" * 300, "score": 0.0, "query_protected": True},
    ]

    result = SummaryPruner(
        context_char_budget=1_000,
        min_community_chars=10,
        max_community_chars=100,
        max_community_share=0.1,
    ).select_top_chunks(ranked, chunks)

    allocation = result["context_allocation"]
    protected = next(item for item in allocation["selected_chunks"] if item["chunk_id"] == 1)
    protected_community = next(
        item for item in allocation["communities"] if item["community_id"] == 1
    )
    assert allocation["consumed_characters"] <= allocation["character_budget"]
    assert protected["query_protection_reservation"] == "reserved"
    assert protected_community["query_protected_reserve_characters"] == protected["character_cost"]
    assert protected_community["query_protected_budget_override"] is True


def test_query_protected_chunk_that_cannot_fit_records_safe_rejection():
    ranked = _ranked([
        {"node": "chunk_0", "type": "chunk", "community": 0, "rank": 1, "composite_score": 0.0, "text_preview": "protected"},
    ])
    result = SummaryPruner(context_char_budget=100).select_top_chunks(
        ranked,
        [{"chunk_id": 0, "text": "P" * 1_000, "score": 0.0, "query_protected": True}],
    )

    rejected = result["context_allocation"]["rejected_chunks"]
    assert result["global_top_chunks"] == []
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "query_protected_exceeds_total_budget"
    assert rejected[0]["safety_action"] == "not_selected_to_preserve_character_budget"
    assert rejected[0]["character_cost"] > 100


def test_allocator_consumes_normalized_path_score_when_available_deterministically():
    ranked = _ranked([
        {"node": "chunk_0", "type": "chunk", "community": 0, "rank": 1, "composite_score": 0.5, "normalized_path_score": 0.0, "text_preview": "a"},
        {"node": "chunk_1", "type": "chunk", "community": 0, "rank": 2, "composite_score": 0.5, "normalized_path_score": 1.0, "text_preview": "b"},
    ])
    chunks = [
        {"chunk_id": 0, "text": "first evidence", "score": 0.5},
        {"chunk_id": 1, "text": "second evidence", "score": 0.5},
    ]

    pruner = SummaryPruner(context_char_budget=500, min_community_chars=100, max_community_chars=400)
    first = pruner.select_top_chunks(ranked.sample(frac=1, random_state=4), chunks)
    second = pruner.select_top_chunks(ranked.sample(frac=1, random_state=8), chunks)

    assert first["context_allocation"]["path_signal_status"] == "available"
    assert [item["chunk_id"] for item in first["global_top_chunks"]] == [1, 0]
    assert first["context_allocation"] == second["context_allocation"]


def test_prompt_emits_budget_metadata_and_blocks_provider_overflow():
    pruned = {
        "context_allocation": {
            "character_budget": 1_000,
            "communities": [{"community_id": 3, "allocated_characters": 800}],
        },
        "communities": [{
            "community_id": 3,
            "chunks": [{
                "chunk_id": "c1",
                "text": "evidence " * 100,
                "allocation": {"character_cost": 900},
            }],
        }],
    }

    prompt = PromptBuilder(
        provider_context_token_limit=200,
        reserved_output_tokens=50,
    ).build_all_community_prompts(pruned)[0]

    assert prompt["budget"] == {
        "selected_chunk_count": 1,
        "selected_character_cost": 900,
        "community_character_budget": 800,
        "total_character_budget": 1_000,
    }
    assert prompt["provider_safety"]["status"] == "blocked"
    assert prompt["provider_safety"]["estimated_total_tokens"] > 200

    class Session:
        def call_llm(self, *_args):
            raise AssertionError("unsafe prompt must not reach a provider")

    summary = LLMSummarizer(session=Session()).summarize_communities([prompt])[0]
    assert summary["summary"] == ""
    assert summary["skip_reason"] == "provider_token_budget_exceeded"


def test_query_protection_marks_only_original_retrieval_hits_after_parent_expansion():
    from launcher.runners import _mark_retrieval_hits_query_protected, _with_current_query_protection

    chunks = [
        {"chunk_uid": "paper:chunk:hit", "chunk_id": 1, "query_protected": True},
        {"chunk_uid": "paper:chunk:parent", "chunk_id": 0, "query_protected": True},
    ]
    protected = _mark_retrieval_hits_query_protected(chunks, {("uid", "paper:chunk:hit")})

    assert protected == {"paper:chunk:hit"}
    assert [chunk["query_protected"] for chunk in chunks] == [True, False]

    report = _with_current_query_protection(
        {"elements": [{"canonical_id": "ent_hit"}, {"canonical_id": "ent_parent"}]},
        {"canonical_entities": [
            {"canonical_id": "ent_hit", "chunk_uids": ["paper:chunk:hit"]},
            {"canonical_id": "ent_parent", "chunk_uids": ["paper:chunk:parent"]},
        ]},
        chunks,
    )
    assert report["query_protected"] == ["ent_hit"]
