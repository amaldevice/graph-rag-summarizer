import json
from pathlib import Path
import sys
import types

import networkx as nx
import pandas as pd
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from evaluation.evaluator import SummaryEvaluator
from evaluation.quality_checker import QualityChecker
from graph.graph_builder import GraphBuilder
from graph.graph_analyzer import GraphAnalyzer
from launcher.runners import _evaluation_source_chunks
from pipeline.feedback_loop import FeedbackLoopController
from summarizer.hierarchical_reducer import HierarchicalReducer
from summarizer.prompt_builder import PromptBuilder
from summarizer.pruner import SummaryPruner
from vectordb.qdrant_handler import QdrantHandler


def test_qdrant_preserves_hierarchy_payload_on_upsert_and_retrieval():
    captured = {}

    class FakeClient:
        def upsert(self, collection_name, points):
            captured["points"] = points

    chunk = {
        "chunk_id": 4,
        "text": "Sentence level evidence.",
        "level": "sentence",
        "hierarchy": {"level": "sentence", "section": "Findings", "paragraph_index": 2, "sentence_index": 1},
        "layout": {"kind": "text", "page_no": 5},
        "source": "paper.pdf",
        "page_no": 5,
    }
    handler = QdrantHandler(client=FakeClient(), collection_name="test")
    handler.upsert_chunks([chunk], [[0.1, 0.2]])
    payload = captured["points"][0].payload
    assert payload["hierarchy"] == chunk["hierarchy"]
    assert payload["layout"] == chunk["layout"]

    class FakeResult:
        def __init__(self, payload):
            self.id = 4
            self.score = 0.7
            self.payload = payload

    handler.search = lambda query_vector, limit=1: [FakeResult(payload)]
    retrieved = handler.search_as_chunks([0.1, 0.2], limit=1)[0]
    assert retrieved["hierarchy"]["section"] == "Findings"
    assert retrieved["layout"]["kind"] == "text"


def test_path_aware_pruner_adds_path_evidence_to_selected_chunks():
    ranked = pd.DataFrame([
        {"node": "chunk_0", "type": "chunk", "community": 0, "rank": 1, "composite_score": 0.9, "pagerank": 0.9, "text_preview": "A"},
        {"node": "chunk_1", "type": "chunk", "community": 0, "rank": 2, "composite_score": 0.2, "pagerank": 0.2, "text_preview": "B"},
        {"node": "ent_bridge", "type": "entity", "community": 0, "rank": 3, "composite_score": 0.8, "pagerank": 0.8, "text_preview": "bridge"},
    ])
    graph = nx.Graph()
    graph.add_edge("chunk_0", "ent_bridge", weight=1.0, edge_type="mentions")
    graph.add_edge("ent_bridge", "chunk_1", weight=1.0, edge_type="mentions")
    chunks = [
        {"chunk_id": 0, "text": "A", "score": 0.9, "level": "paragraph", "source": "paper"},
        {"chunk_id": 1, "text": "B", "score": 0.95, "level": "paragraph", "source": "paper"},
    ]

    result = SummaryPruner(top_k_per_community=2, top_k_global=2).select_top_chunks(ranked, chunks, graph=graph)

    selected = result["communities"][0]["chunks"]
    assert {c["chunk_id"] for c in selected} == {0, 1}
    assert any(c["path_evidence"] for c in selected)
    assert result["selection_strategy"] == "path_aware"


def test_path_aware_pruner_keeps_repeated_local_ids_from_different_documents_separate():
    ranked = pd.DataFrame([
        {"node": "chunk_0", "type": "chunk", "community": 0, "rank": 1, "composite_score": 0.9, "text_preview": "A"},
        {"node": "chunk_1", "type": "chunk", "community": 0, "rank": 2, "composite_score": 0.8, "text_preview": "B"},
    ])
    chunks = [
        {"chunk_id": 0, "chunk_uid": "paper-a:chunk:0", "document_id": "paper-a", "text": "A", "score": 0.9},
        {"chunk_id": 0, "chunk_uid": "paper-b:chunk:0", "document_id": "paper-b", "text": "B", "score": 0.8},
    ]

    result = SummaryPruner(top_k_per_community=2, top_k_global=2).select_top_chunks(ranked, chunks)

    selected = result["communities"][0]["chunks"]
    assert {chunk["chunk_id"] for chunk in selected} == {"paper-a:chunk:0", "paper-b:chunk:0"}
    assert {chunk["document_id"] for chunk in selected} == {"paper-a", "paper-b"}


def test_pruner_expands_selected_sentence_with_bounded_parent_context():
    ranked = pd.DataFrame([
        {"node": "chunk_2", "type": "chunk", "community": 0, "rank": 1, "composite_score": 0.9, "text_preview": "Sentence evidence supports the reported finding in this section clearly."},
    ])
    chunks = [
        {
            "chunk_id": 0,
            "text": "Findings",
            "level": "section",
            "hierarchy": {"section_id": "section:1", "path": ["section:1"]},
        },
        {
            "chunk_id": 1,
            "text": "The paragraph provides context.",
            "level": "paragraph",
            "hierarchy": {
                "section_id": "section:1",
                "paragraph_id": "paragraph:1",
                "parent_id": "section:1",
                "parent_chunk_id": 0,
                "path": ["section:1", "paragraph:1"],
            },
        },
        {
            "chunk_id": 2,
            "text": "Sentence evidence supports the reported finding in this section clearly.",
            "level": "sentence",
            "hierarchy": {
                "section_id": "section:1",
                "paragraph_id": "paragraph:1",
                "parent_id": "paragraph:1",
                "parent_chunk_id": 1,
                "path": ["section:1", "paragraph:1", "sentence:1"],
            },
        },
    ]

    result = SummaryPruner(top_k_per_community=1, top_k_global=1).select_top_chunks(ranked, chunks)

    selected = result["communities"][0]["chunks"][0]
    assert [item["chunk_id"] for item in selected["parent_context"]] == [1, 0]
    assert selected["context_expansion"] == {"added_parent_count": 2, "max_depth": 2}
    assert selected["parent_context"][0]["text"] == "The paragraph provides context."


def test_pruner_filters_tiny_sentences_but_keeps_short_sections():
    ranked = pd.DataFrame([
        {"node": "chunk_0", "type": "chunk", "community": 0, "rank": 1, "composite_score": 0.99, "text_preview": "Let Me."},
        {"node": "chunk_1", "type": "chunk", "community": 0, "rank": 2, "composite_score": 0.8, "text_preview": "Methods"},
    ])
    chunks = [
        {"chunk_id": 0, "text": "Let Me.", "level": "sentence"},
        {"chunk_id": 1, "text": "Methods", "level": "section"},
    ]

    result = SummaryPruner(top_k_per_community=2, top_k_global=2).select_top_chunks(ranked, chunks)

    selected = result["communities"][0]["chunks"]
    assert [chunk["chunk_id"] for chunk in selected] == [1]
    assert result["filtered_chunks"] == [{
        "chunk_id": 0,
        "reason": "tiny_sentence",
        "word_count": 2,
        "min_sentence_words": 8,
    }]


def test_prompt_builder_includes_expanded_parent_context():
    prompt = PromptBuilder().build_community_prompt(
        0,
        [{
            "chunk_id": 2,
            "text": "Sentence evidence.",
            "level": "sentence",
            "parent_context": [{"chunk_id": 1, "level": "paragraph", "text": "The paragraph provides context."}],
        }],
    )

    assert "parent_context:" in prompt
    assert "The paragraph provides context." in prompt


def test_graph_builder_links_chunks_to_mentioned_entities():
    graph = GraphBuilder(knn_k=1, sim_threshold=0.99).build_graph(
        chunks=[
            {"chunk_id": "c0", "text": "Alpha appears here.", "level": "sentence"},
            {"chunk_id": "c1", "text": "Beta appears here.", "level": "sentence"},
        ],
        chunk_embeddings=[[1.0, 0.0], [0.0, 1.0]],
        all_entities=[
            {"chunk_id": "c0", "text": "Alpha", "label": "ORG"},
            {"chunk_id": "c1", "text": "Beta", "label": "ORG"},
        ],
        all_relations=[],
    )

    assert graph.has_edge("chunk_0", "ent_alpha")
    assert graph["chunk_0"]["ent_alpha"]["edge_type"] == "mentions"
    assert graph.has_edge("chunk_1", "ent_beta")


def test_graph_builder_uses_document_safe_chunk_keys_when_local_ids_repeat():
    graph = GraphBuilder(knn_k=1, sim_threshold=0.99).build_graph(
        chunks=[
            {"chunk_id": 0, "chunk_uid": "paper-a:chunk:0", "text": "Alpha", "level": "sentence"},
            {"chunk_id": 0, "chunk_uid": "paper-b:chunk:0", "text": "Beta", "level": "sentence"},
        ],
        chunk_embeddings=[[1.0, 0.0], [0.0, 1.0]],
        all_entities=[
            {"chunk_id": 0, "chunk_uid": "paper-a:chunk:0", "text": "Alpha", "label": "ORG"},
            {"chunk_id": 0, "chunk_uid": "paper-b:chunk:0", "text": "Beta", "label": "ORG"},
        ],
        all_relations=[],
    )

    assert graph.has_edge("chunk_0", "ent_alpha")
    assert graph.has_edge("chunk_1", "ent_beta")


def test_graph_builder_excludes_context_only_parent_chunks():
    graph = GraphBuilder(knn_k=1, sim_threshold=0.0).build_graph(
        chunks=[
            {"chunk_id": 0, "context_only": True, "text": "Parent context", "level": "paragraph"},
            {"chunk_id": 1, "text": "Main evidence", "level": "sentence"},
        ],
        chunk_embeddings=[[1.0, 0.0], [0.0, 1.0]],
        all_entities=[],
        all_relations=[],
    )

    assert not graph.has_node("chunk_0")
    assert graph.has_node("chunk_1")


def test_prompt_builder_uses_nap_cap_cgm_sections():
    prompt = PromptBuilder().build_community_prompt(
        3,
        [{
            "chunk_id": 7,
            "rank": 1,
            "composite_score": 0.8,
            "level": "paragraph",
            "hierarchy": {"section": "Findings"},
            "path_evidence": [{"path": ["chunk_7", "ent_x", "chunk_8"]}],
            "text": "Grounded fact.",
        }],
        query="Summarize findings",
    )
    assert "NAP" in prompt
    assert "CAP" in prompt
    assert "CGM" in prompt
    assert "path_evidence" in prompt
    assert "Findings" in prompt


def test_raptor_reducer_creates_levels_for_large_inputs():
    calls = []

    class FakeSession:
        def call_llm(self, system_prompt, prompt):
            calls.append(prompt)
            return f"summary-{len(calls)}"

    class FakeEmbedder:
        def embed_text(self, text):
            return [float(len(text) % 3), 0.0]

    reducer = HierarchicalReducer(session=FakeSession(), embedder=FakeEmbedder(), raptor_group_size=2)
    result = reducer.reduce_summaries(
        [
            {"community_id": idx, "summary": f"community {idx}", "chunk_ids": [idx]}
            for idx in range(5)
        ],
        query="main idea",
    )

    assert result["reduction_strategy"] == "raptor"
    assert len(result["reduction_levels"]) >= 2
    assert result["final_summary"] == f"summary-{len(calls)}"


def test_raptor_reducer_groups_embedding_similar_summaries_before_merging():
    class FakeSession:
        def __init__(self):
            self.calls = 0

        def call_llm(self, _system_prompt, _prompt):
            self.calls += 1
            return f"merged-{self.calls}"

    class FakeEmbedder:
        vectors = {
            "topic alpha": [1.0, 0.0],
            "topic beta": [0.0, 1.0],
            "topic alpha related": [0.9, 0.1],
            "topic beta related": [0.1, 0.9],
            "topic mixed": [0.5, 0.5],
        }

        def __init__(self):
            self.calls = []

        def embed_text(self, text):
            self.calls.append(text)
            return self.vectors.get(text, [0.5, 0.5])

    embedder = FakeEmbedder()
    result = HierarchicalReducer(
        session=FakeSession(), embedder=embedder, raptor_group_size=2
    ).reduce_summaries([
        {"community_id": 0, "summary": "topic alpha", "chunk_ids": [0]},
        {"community_id": 1, "summary": "topic beta", "chunk_ids": [1]},
        {"community_id": 2, "summary": "topic alpha related", "chunk_ids": [2]},
        {"community_id": 3, "summary": "topic beta related", "chunk_ids": [3]},
        {"community_id": 4, "summary": "topic mixed", "chunk_ids": [4]},
    ])

    first_level = result["reduction_levels"][0]
    assert first_level["grouping_strategy"] == "embedding_similarity"
    assert [group["source_ids"] for group in first_level["groups"]] == [[0, 2], [1, 3], [4]]
    assert set(embedder.calls) >= {
        "topic alpha", "topic beta", "topic alpha related", "topic beta related", "topic mixed",
    }
    assert len(embedder.calls) > 5


def test_raptor_reducer_reports_stable_id_fallback_for_invalid_embeddings():
    class FakeSession:
        def call_llm(self, _system_prompt, _prompt):
            return "merged"

    class InvalidEmbedder:
        def embed_text(self, _text):
            return None

    result = HierarchicalReducer(
        session=FakeSession(), embedder=InvalidEmbedder(), raptor_group_size=2
    ).reduce_summaries([
        {"community_id": 2, "summary": "two", "chunk_ids": [2]},
        {"community_id": 0, "summary": "zero", "chunk_ids": [0]},
        {"community_id": 1, "summary": "one", "chunk_ids": [1]},
    ])

    first_level = result["reduction_levels"][0]
    assert first_level["grouping_strategy"] == "stable_id_order_fallback"
    assert [group["source_ids"] for group in first_level["groups"]] == [[0, 1], [2]]


def test_evaluator_reports_grounded_metric_statuses_without_optional_models():
    result = SummaryEvaluator().evaluate_without_reference(
        "alpha beta",
        source_chunks=[{"text": "alpha beta gamma"}],
        query="What is alpha?",
    )
    metrics = result["grounded_metrics"]
    assert set(metrics) == {
        "factcc", "summac", "geval", "qa_coverage",
        "entity_consistency", "number_date_consistency", "sentence_support",
        "citation_coverage", "redundancy", "query_relevance", "evidence_diversity",
    }
    assert metrics["factcc"]["status"] in {"available", "unavailable"}
    assert metrics["summac"]["status"] in {"available", "unavailable"}
    assert metrics["geval"]["status"] in {"available", "unavailable"}
    assert metrics["qa_coverage"]["status"] == "available"

    quality = QualityChecker(min_summary_words=1).check(result)
    assert "metric_decisions" in quality
    assert QualityChecker(min_summary_words=1).suggest_action(quality)["action"] in {"accept", "retry_retrieval", "retry_prompt", "retry_reduce", "manual_review", "review"}


def test_evaluation_uses_explicit_selected_evidence_without_raw_retrieval_fallback():
    retrieved_chunks = [{"chunk_id": "raw", "text": "Raw retrieval evidence."}]

    assert _evaluation_source_chunks({"global_top_chunks": []}, retrieved_chunks) == []
    assert _evaluation_source_chunks({"communities": []}, retrieved_chunks) == retrieved_chunks


def test_feedback_controller_maps_actions_to_retry_stages():
    controller = FeedbackLoopController(max_retries=2)
    base = {"retrieval_retries": 0, "prompt_retries": 0, "reduce_retries": 0, "total_retries": 0}
    retrieval = controller.decide({"status": "FAIL"}, {"action": "retry_retrieval"}, base)
    prompt = controller.decide({"status": "FAIL"}, {"action": "retry_prompt"}, base)
    reduce = controller.decide({"status": "FAIL"}, {"action": "retry_reduce"}, base)
    assert retrieval["next_stage"] == "retrieval"
    assert prompt["next_stage"] == "prompt"
    assert reduce["next_stage"] == "reduce"


@pytest.mark.parametrize(
    ("forced_stage", "expected_calls"),
    [
        ("retrieval", {"retrieval": 2, "graph": 2, "summarize": 2, "reduce": 2}),
        ("prompt", {"retrieval": 1, "graph": 1, "summarize": 2, "reduce": 2}),
        ("reduce", {"retrieval": 1, "graph": 1, "summarize": 1, "reduce": 2}),
    ],
)
def test_full_pipeline_forced_retry_reruns_expected_stage(monkeypatch, tmp_path, forced_stage, expected_calls):
    from config import settings

    calls = {"retrieval": 0, "graph": 0, "summarize": 0, "reduce": 0, "decision": 0, "evaluation_sources": []}
    graph_failure = {"enabled": False}
    modules = {name: types.ModuleType(name) for name in [
        "embedding.embedder", "vectordb.qdrant_handler", "preprocessing.docling_loader",
        "graph.entity_extractor", "graph.graph_builder", "graph.community_detector",
        "graph.graph_analyzer", "summarizer.pruner", "summarizer.prompt_builder",
        "summarizer.provider_router", "summarizer.llm_summarizer", "summarizer.hierarchical_reducer",
        "evaluation.evaluator", "evaluation.quality_checker", "pipeline.feedback_loop",
    ]}

    class FakeEmbedder:
        def embed_text(self, text): return [0.1, 0.2]

    class FakeQdrant:
        def __init__(self, collection_name="test"): pass
        def revalidate_query_authorization(self): pass
        def search_as_chunks(self, query_vector, limit):
            calls["retrieval"] += 1
            return [{"chunk_id": 1, "text": "alpha beta", "page_no": 1, "score": 0.9}]

    class FakeExtractor:
        def __init__(self, provider_router=None): pass
        def extract_entities(self, chunks): return {1: []}, []
        def extract_relations_llm(self, text, entities): return []

    class FakeGraphBuilder:
        def build_graph(self, *args):
            calls["graph"] += 1
            if graph_failure["enabled"]:
                raise RuntimeError("compatibility graph unavailable")
            return nx.Graph()

    class FakeDetector:
        def detect(self, graph): return graph, {0: ["chunk_0"]}, {}, 0.1

    class FakeAnalyzer:
        def analyze(self, graph): return pd.DataFrame([{"node": "chunk_0", "type": "chunk", "community": 0, "rank": 1, "composite_score": 1.0, "text_preview": "alpha"}])
        def save_ranked_csv(self, ranked, output_path): return output_path
        def save_ranked_json(self, ranked, output_path): return output_path
        def save_summary_json(self, ranked, communities, modularity, output_path, relation_extraction_mode="unavailable", *args, **kwargs): return output_path

    class FakePruner:
        def __init__(self, top_k_per_community, top_k_global): pass
        def select_top_chunks(self, ranked, chunks, graph=None): return {"communities": [{"community_id": 0, "chunks": chunks}]}
        def save_pruned_json(self, result, output_path): return output_path
        def save_pruned_csv(self, result, output_path): return output_path

    class FakePromptBuilder:
        def __init__(self, max_chars_per_chunk): pass
        def build_all_community_prompts(self, result, query, style): return [{"community_id": 0, "prompt": "prompt", "chunk_ids": [1]}]

    class FakeSummarizer:
        def __init__(self, session=None): pass
        def summarize_communities(self, prompts):
            calls["summarize"] += 1
            return [{"community_id": 0, "summary": f"map {calls['summarize']}", "chunk_ids": [1]}]
        def save_map_summaries_json(self, summaries, output_path): return output_path
        def save_map_summaries_txt(self, summaries, output_path): return output_path

    class FakeReducer:
        def __init__(self, session=None, embedder=None): pass
        def reduce_summaries(self, summaries, query, style):
            calls["reduce"] += 1
            return {"final_summary": f"final {calls['reduce']}"}
        def save_final_summary_json(self, result, output_path): return output_path
        def save_final_summary_txt(self, result, output_path): return output_path

    class FakeEvaluator:
        def __init__(self, judge_session=None): pass
        def evaluate_without_reference(self, generated_summary, source_chunks, query=None):
            calls["evaluation_sources"].append(source_chunks)
            return {"generated_length": 10, "has_reference": False}
        def save_evaluation_json(self, result, output_path): return output_path

    class FakeQuality:
        def check(self, result): return {"status": "PASS"}
        def suggest_action(self, quality): return {"action": "accept"}
        def save_quality_report(self, quality, action, output_path):
            Path(output_path).write_text(json.dumps({
                "quality_result": quality,
                "suggested_action": action,
            }))
            return output_path

    class FakeFeedback:
        def __init__(self, max_retries): pass
        def decide(self, quality_result, action_result, retry_state):
            calls["decision"] += 1
            action = action_result["action"]
            if action.startswith("retry_"):
                stage = action.removeprefix("retry_")
                return {
                    "stop": False,
                    "next_stage": stage,
                    "updated_retry_state": {"total_retries": 1},
                    "final_decision": None,
                }
            return {"stop": True, "next_stage": None, "updated_retry_state": retry_state, "final_decision": "accept"}
        def save_decision(self, decision, output_path):
            Path(output_path).write_text(json.dumps(decision))
            return output_path

    modules["embedding.embedder"].TextEmbedder = FakeEmbedder
    modules["vectordb.qdrant_handler"].QdrantHandler = FakeQdrant
    modules["preprocessing.docling_loader"].DoclingLoader = object
    modules["graph.entity_extractor"].EntityExtractor = FakeExtractor
    modules["graph.graph_builder"].GraphBuilder = FakeGraphBuilder
    modules["graph.community_detector"].CommunityDetector = FakeDetector
    modules["graph.graph_analyzer"].GraphAnalyzer = FakeAnalyzer
    # Keep the new allocator real at the runner seam; other pipeline stages
    # remain fakes so the retry assertion stays isolated.
    modules["summarizer.pruner"].SummaryPruner = SummaryPruner
    modules["summarizer.prompt_builder"].PromptBuilder = FakePromptBuilder
    modules["summarizer.provider_router"].create_session = lambda: object()
    modules["summarizer.llm_summarizer"].LLMSummarizer = FakeSummarizer
    modules["summarizer.hierarchical_reducer"].HierarchicalReducer = FakeReducer
    modules["evaluation.evaluator"].SummaryEvaluator = FakeEvaluator
    modules["evaluation.quality_checker"].QualityChecker = FakeQuality
    modules["pipeline.feedback_loop"].FeedbackLoopController = FakeFeedback
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(settings, "ENABLE_ON_DEMAND_PAGE_RENDER", False)

    from launcher.runners import run_full_pipeline
    monkeypatch.setattr("launcher.runners._configure_query_denial", lambda *args: None)
    artifact_dir = tmp_path / "test"
    run_full_pipeline({
        "collection": "c",
        "query": "q",
        "retrieval_limit": 3,
        "artifact_dir": str(artifact_dir),
        "verbose": False,
        "_test_force_feedback_retry_stage": forced_stage,
    })

    assert {name: calls[name] for name in expected_calls} == expected_calls
    assert all("path_evidence" in chunk for chunks in calls["evaluation_sources"] for chunk in chunks)
    for current_dir, attempt in ((artifact_dir, 0), (artifact_dir / "attempt-1", 1)):
        allocation = json.loads((current_dir / "context_allocation.json").read_text())
        assert allocation["character_budget"] == 12_000
        assert allocation["runner_context"] == {
            "attempt": attempt,
            "allocator_status": "available",
            "collection_mode": "document-safe",
            "graph_source": "compatibility_query_graph",
            "fallback_status": "persistent_graph_disabled",
            "fallback_reason": "",
            "query_protected_chunk_uids": ["1"],
        }
    base_quality = json.loads((artifact_dir / "quality_gate_report.json").read_text())
    base_decision = json.loads((artifact_dir / "feedback_loop_decision.json").read_text())
    retry_decision = json.loads((artifact_dir / "attempt-1" / "feedback_loop_decision.json").read_text())
    assert base_quality["quality_result"]["forced_failure"] == {
        "stage": forced_stage, "attempt": 0, "test_only": True,
    }
    assert base_quality["suggested_action"]["action"] == f"retry_{forced_stage}"
    assert base_decision["next_stage"] == forced_stage
    assert base_decision["attempt"] == 0
    assert retry_decision["attempt"] == 1

    graph_failure["enabled"] = True
    fallback_dir = tmp_path / "vector-only"
    run_full_pipeline({"collection": "c", "query": "q", "retrieval_limit": 3, "artifact_dir": str(fallback_dir), "verbose": False})

    fallback = json.loads((fallback_dir / "context_allocation.json").read_text())
    assert fallback["runner_context"] == {
        "attempt": 0,
        "allocator_status": "available",
        "collection_mode": "document-safe",
        "graph_source": "vector_only",
        "fallback_status": "compatibility_graph_failed",
        "fallback_reason": "RuntimeError: compatibility graph unavailable",
        "query_protected_chunk_uids": ["1"],
    }
    assert json.loads((fallback_dir / "graph_fallback.json").read_text()) == {
        "graph_source": "vector_only",
        "fallback_status": "compatibility_graph_failed",
        "fallback_reason": "RuntimeError: compatibility graph unavailable",
    }


def test_docling_chunk_text_adds_hierarchy_for_sections_and_sentences():
    from preprocessing.docling_loader import DoclingLoader

    class TitleItem:
        text = "Findings"
        page_no = 1

    class ParagraphItem:
        text = "First finding. Second finding."
        page_no = 1

    class FakeDocument:
        def iterate_items(self):
            yield TitleItem(), None
            yield ParagraphItem(), None

    class FakeResult:
        document = FakeDocument()

    chunks = DoclingLoader.__new__(DoclingLoader).chunk_text(FakeResult(), source_name="paper.pdf")

    assert chunks[0]["level"] == "section"
    assert chunks[0]["hierarchy"]["section"] == "Findings"
    assert [c["level"] for c in chunks[1:]] == ["paragraph", "sentence", "sentence"]
    assert chunks[1]["hierarchy"]["paragraph_id"] == "paragraph:1"
    assert chunks[1]["hierarchy"]["parent_id"] == "section:1"
    assert chunks[2]["hierarchy"]["parent_chunk_id"] == chunks[1]["chunk_id"]
    assert chunks[2]["hierarchy"]["sentence_index"] == 1
    assert chunks[3]["hierarchy"]["sentence_index"] == 2


def test_docling_single_sentence_gets_context_only_paragraph_parent():
    from preprocessing.docling_loader import DoclingLoader

    class TitleItem:
        text = "Methods"
        page_no = 1

    class SentenceItem:
        text = "A short but meaningful statement."
        page_no = 1

    class FakeDocument:
        def iterate_items(self):
            yield TitleItem(), None
            yield SentenceItem(), None

    class FakeResult:
        document = FakeDocument()

    chunks = DoclingLoader.__new__(DoclingLoader).chunk_text(FakeResult(), source_name="paper.pdf")

    assert [chunk["level"] for chunk in chunks] == ["section", "paragraph", "sentence"]
    assert chunks[1]["context_only"] is True
    assert chunks[2]["hierarchy"]["parent_chunk_id"] == chunks[1]["chunk_id"]
    assert chunks[2]["hierarchy"]["parent_id"] == "paragraph:1"
