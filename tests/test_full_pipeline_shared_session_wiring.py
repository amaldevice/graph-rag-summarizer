from copy import deepcopy
import json
import sys
import types
from pathlib import Path

import networkx as nx

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import settings


def test_full_pipeline_uses_one_provider_session_for_summarizer_and_reducer(monkeypatch, tmp_path):
    shared_session = object()
    received_sessions = []
    saved_paths = {}
    received_extractor_session = []
    graph_inputs = {}
    feedback_decisions = [{"final_decision": "stop"}]

    embedder_module = types.ModuleType("embedding.embedder")
    qdrant_module = types.ModuleType("vectordb.qdrant_handler")
    docling_module = types.ModuleType("preprocessing.docling_loader")
    entity_module = types.ModuleType("graph.entity_extractor")
    graph_builder_module = types.ModuleType("graph.graph_builder")
    community_module = types.ModuleType("graph.community_detector")
    analyzer_module = types.ModuleType("graph.graph_analyzer")
    pruner_module = types.ModuleType("summarizer.pruner")
    prompt_builder_module = types.ModuleType("summarizer.prompt_builder")
    provider_router_module = types.ModuleType("summarizer.provider_router")
    summarizer_module = types.ModuleType("summarizer.llm_summarizer")
    reducer_module = types.ModuleType("summarizer.hierarchical_reducer")
    evaluator_module = types.ModuleType("evaluation.evaluator")
    quality_module = types.ModuleType("evaluation.quality_checker")
    feedback_module = types.ModuleType("pipeline.feedback_loop")

    class FakeEmbedder:
        def embed_text(self, text: str):
            del text
            return [0.1, 0.2]

    class FakeQdrantHandler:
        def __init__(self, collection_name="test"):
            del collection_name
            self.denied_document_ids = set()

        def set_denied_document_ids(self, document_ids):
            self.denied_document_ids = set(document_ids)

        def revalidate_query_authorization(self):
            pass

        def search_as_chunks(self, query_vector, limit: int):
            del query_vector, limit
            assert "tombstoned" in self.denied_document_ids
            return [{"chunk_id": "c1", "text": "chunk text", "page_no": 1}]

    class FakeEntityExtractor:
        relation_extraction_mode = "llm-enhanced"

        def __init__(self, provider_router=None):
            received_extractor_session.append(provider_router)

        def extract_entities(self, chunks):
            del chunks
            entities = [
                {
                    "chunk_id": "c1",
                    "chunk_uid": "c1",
                    "text": "Alpha",
                    "label": "ORG",
                    "sentence_index": 0,
                },
                {
                    "chunk_id": "c1",
                    "chunk_uid": "c1",
                    "text": "Beta",
                    "label": "ORG",
                    "sentence_index": 0,
                },
                {
                    "chunk_id": "c1",
                    "chunk_uid": "c1",
                    "text": "Gamma",
                    "label": "ORG",
                    "sentence_index": 0,
                },
            ]
            return {"c1": entities}, entities

        def extract_relations_llm(self, text, entities):
            del text, entities
            return [
                {"head": "Alpha", "relation": "supports", "tail": "Beta"},
                {
                    "head": "Alpha",
                    "relation": "co-occurs_with",
                    "tail": "Beta",
                    "source": "fallback",
                },
            ]

    class FakeGraphBuilder:
        def build_graph(self, retrieved_chunks, chunk_embeddings, all_entities, all_relations):
            del retrieved_chunks, chunk_embeddings
            graph_inputs["entities"] = all_entities
            graph_inputs["relations"] = all_relations
            graph = nx.Graph()
            graph.add_nodes_from(entity["canonical_id"] for entity in all_entities)
            graph.add_edge("ent_alpha", "ent_beta")
            return graph

    class FakeCommunityDetector:
        def detect(self, graph):
            return graph, [[1]], {}, 0.0

    class FakeRanked:
        def head(self, count: int):
            del count
            return self

        def to_string(self, index: bool = False):
            del index
            return "ranked"

    class FakeGraphAnalyzer:
        def analyze(self, graph):
            del graph
            return FakeRanked()

        def save_ranked_csv(self, ranked, output_path="output/graph_ranked_nodes.csv"):
            del ranked
            saved_paths["graph_ranked_csv"] = output_path
            return output_path

        def save_ranked_json(self, ranked, output_path="output/graph_ranked_nodes.json"):
            del ranked
            saved_paths["graph_ranked_json"] = output_path
            return output_path

        def save_summary_json(
            self,
            ranked,
            communities,
            modularity,
            output_path="output/graph_summary.json",
            relation_extraction_mode="unavailable",
            *args, **kwargs,
        ):
            del ranked, communities, modularity
            saved_paths["graph_summary_json"] = output_path
            saved_paths["graph_summary"] = {"relation_extraction": {"mode": relation_extraction_mode}}
            return output_path

    class FakeSummaryPruner:
        def __init__(self, top_k_per_community: int, top_k_global: int):
            del top_k_per_community, top_k_global

        def select_top_chunks(self, ranked, retrieved_chunks):
            del ranked, retrieved_chunks
            return {"communities": [{"community_id": 0, "chunk_ids": ["c1"], "num_chunks": 1}]}

        def save_pruned_json(self, pruned_result, output_path="output/pruned_summary_context.json"):
            del pruned_result
            saved_paths["pruned_json"] = output_path
            return output_path

        def save_pruned_csv(self, pruned_result, output_path="output/pruned_summary_context.csv"):
            del pruned_result
            saved_paths["pruned_csv"] = output_path
            return output_path

    class FakePromptBuilder:
        def __init__(self, max_chars_per_chunk: int):
            del max_chars_per_chunk

        def build_all_community_prompts(self, pruned_result, query: str, style: str):
            del pruned_result, query, style
            return [{"community_id": 0, "prompt": "summarize", "chunk_ids": ["c1"], "num_chunks": 1}]

    def fake_create_session():
        return shared_session

    class FakeSummarizer:
        def __init__(self, session=None):
            received_sessions.append(("summarizer", session))

        def summarize_communities(self, community_prompts):
            del community_prompts
            return [{"community_id": 0, "summary": "community summary", "chunk_ids": ["c1"]}]

        def save_map_summaries_json(self, community_summaries, output_path="output/community_map_summaries.json"):
            del community_summaries
            saved_paths["map_json"] = output_path
            return output_path

        def save_map_summaries_txt(self, community_summaries, output_path="output/community_map_summaries.txt"):
            del community_summaries
            saved_paths["map_txt"] = output_path
            return output_path

    class FakeReducer:
        def __init__(self, session=None):
            received_sessions.append(("reducer", session))

        def reduce_summaries(self, community_summaries, query: str, style: str):
            del community_summaries, query, style
            return {"final_summary": "done"}

        def save_final_summary_json(self, final_result, output_path="output/final_summary.json"):
            del final_result
            saved_paths["final_json"] = output_path
            return output_path

        def save_final_summary_txt(self, final_result, output_path="output/final_summary.txt"):
            del final_result
            saved_paths["final_txt"] = output_path
            return output_path

    class FakeEvaluator:
        def evaluate_without_reference(self, generated_summary: str, source_chunks):
            del generated_summary, source_chunks
            return {"quality": "ok"}

        def save_evaluation_json(self, eval_result, output_path="output/evaluation_result.json"):
            del eval_result
            saved_paths["evaluation_json"] = output_path
            return output_path

    class FakeQualityChecker:
        def check(self, eval_result):
            del eval_result
            return {"status": "pass"}

        def suggest_action(self, quality_result):
            del quality_result
            return {"action": "none"}

        def save_quality_report(self, quality_result, action_result, output_path="output/quality_gate_report.json"):
            del quality_result, action_result
            saved_paths["quality_json"] = output_path
            return output_path

    class FakeFeedbackLoopController:
        def __init__(self, max_retries: int):
            del max_retries

        def decide(self, quality_result, action_result, retry_state):
            del quality_result, action_result, retry_state
            return feedback_decisions.pop(0)

        def save_decision(self, decision, output_path="output/feedback_loop_decision.json"):
            del decision
            saved_paths["decision_json"] = output_path
            return output_path

    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module.QdrantHandler = FakeQdrantHandler
    docling_module.DoclingLoader = object
    entity_module.EntityExtractor = FakeEntityExtractor
    graph_builder_module.GraphBuilder = FakeGraphBuilder
    community_module.CommunityDetector = FakeCommunityDetector
    analyzer_module.GraphAnalyzer = FakeGraphAnalyzer
    pruner_module.SummaryPruner = FakeSummaryPruner
    prompt_builder_module.PromptBuilder = FakePromptBuilder
    provider_router_module.create_session = fake_create_session
    summarizer_module.LLMSummarizer = FakeSummarizer
    reducer_module.HierarchicalReducer = FakeReducer
    evaluator_module.SummaryEvaluator = FakeEvaluator
    quality_module.QualityChecker = FakeQualityChecker
    feedback_module.FeedbackLoopController = FakeFeedbackLoopController

    stubs = {
        "embedding.embedder": embedder_module,
        "vectordb.qdrant_handler": qdrant_module,
        "preprocessing.docling_loader": docling_module,
        "graph.entity_extractor": entity_module,
        "graph.graph_builder": graph_builder_module,
        "graph.community_detector": community_module,
        "graph.graph_analyzer": analyzer_module,
        "summarizer.pruner": pruner_module,
        "summarizer.prompt_builder": prompt_builder_module,
        "summarizer.provider_router": provider_router_module,
        "summarizer.llm_summarizer": summarizer_module,
        "summarizer.hierarchical_reducer": reducer_module,
        "evaluation.evaluator": evaluator_module,
        "evaluation.quality_checker": quality_module,
        "pipeline.feedback_loop": feedback_module,
    }
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)

    monkeypatch.setattr(settings, "ENABLE_ON_DEMAND_PAGE_RENDER", False)

    from launcher.runners import run_full_pipeline

    def configure_query_safety(qdrant, collection, object_store=None):
        del collection, object_store
        qdrant.set_denied_document_ids(["tombstoned"])

    monkeypatch.setattr("launcher.runners._configure_query_denial", configure_query_safety)

    artifact_dir = tmp_path / "run-1"
    run_full_pipeline({
        "mode": "full-pipeline",
        "profile": "local",
        "collection": "test",
        "query": "test",
        "retrieval_limit": 5,
        "pdf_path": "",
        "json_output": "",
        "artifact_dir": str(artifact_dir),
        "verbose": True,
    })

    assert received_sessions == [
        ("summarizer", shared_session),
        ("reducer", shared_session),
    ]
    assert received_extractor_session == [shared_session]
    assert saved_paths["graph_ranked_csv"] == str(artifact_dir / "graph_ranked_nodes.csv")
    assert saved_paths["graph_ranked_json"] == str(artifact_dir / "graph_ranked_nodes.json")
    assert saved_paths["graph_summary_json"] == str(artifact_dir / "graph_summary.json")
    assert saved_paths["graph_summary"] == {"relation_extraction": {"mode": "llm-enhanced"}}
    assert saved_paths["pruned_json"] == str(artifact_dir / "pruned_summary_context.json")
    assert saved_paths["pruned_csv"] == str(artifact_dir / "pruned_summary_context.csv")
    assert saved_paths["map_json"] == str(artifact_dir / "community_map_summaries.json")
    assert saved_paths["map_txt"] == str(artifact_dir / "community_map_summaries.txt")
    assert saved_paths["final_json"] == str(artifact_dir / "final_summary.json")
    assert saved_paths["final_txt"] == str(artifact_dir / "final_summary.txt")
    assert saved_paths["evaluation_json"] == str(artifact_dir / "evaluation_result.json")
    assert saved_paths["quality_json"] == str(artifact_dir / "quality_gate_report.json")
    assert saved_paths["decision_json"] == str(artifact_dir / "feedback_loop_decision.json")

    relation_evidence = json.loads((artifact_dir / "relation_evidence.json").read_text())
    assert relation_evidence["counts"] == {
        "raw_evidence_count": 2,
        "active_evidence_count": 1,
        "relation_status_counts": {"accepted": 1, "unverified": 1},
    }
    assert relation_evidence["active_evidence"] == [
        relation for relation in relation_evidence["raw_evidence"]
        if relation["relation"] == "supports"
    ]
    fallback = next(
        relation for relation in relation_evidence["raw_evidence"]
        if relation["source"] == "fallback"
    )
    assert fallback["evidence_type"] == "same_sentence"
    assert fallback["support_chunk_uids"] == ["c1"]
    assert json.loads((artifact_dir / "relation_recovery.json").read_text()) == {
        "status": "not_run",
        "reason": "compatibility_fallback",
        "candidate_generation": {
            "generated": [],
            "deduplicated": [],
            "budget_rejected": [],
        },
        "verification": [],
        "cleanup": {
            "removed_entity_ids": [],
            "removed": [],
            "preserved": [],
        },
        "counts": {
            "local": 0,
            "cross_chunk": 0,
            "accepted": 0,
            "rejected": 0,
            "unverified": 0,
        },
    }

    canonicalization = json.loads((artifact_dir / "entity_canonicalization.json").read_text())
    assert [entity["canonical_id"] for entity in canonicalization["canonical_entities"]] == [
        "ent_alpha",
        "ent_beta",
        "ent_gamma",
    ]
    orphan_report = json.loads((artifact_dir / "orphan_node_report.json").read_text())
    assert orphan_report["strongly_supported"] == ["ent_alpha", "ent_beta"]
    assert orphan_report["mention_only"] == ["ent_gamma"]
    assert orphan_report["query_protected"] == ["ent_alpha", "ent_beta", "ent_gamma"]
    by_entity = {entity["canonical_id"]: entity for entity in orphan_report["elements"]}
    assert by_entity["ent_alpha"]["graph_degree"] == 1
    assert by_entity["ent_beta"]["graph_degree"] == 1
    assert by_entity["ent_gamma"]["graph_degree"] == 0
    assert {entity["canonical_id"] for entity in graph_inputs["entities"]} == {
        "ent_alpha",
        "ent_beta",
        "ent_gamma",
    }
    assert graph_inputs["relations"] == relation_evidence["raw_evidence"]

    persistent_dir = tmp_path / "persistent-run"
    persisted_diagnostics = {
        "documents": {
            "persisted-document": {
                "raw_evidence": [{
                    "head": "Persisted Alpha",
                    "relation": "supports",
                    "tail": "Persisted Beta",
                    "status": "accepted",
                }],
                "active_evidence": [{
                    "head": "Persisted Alpha",
                    "relation": "supports",
                    "tail": "Persisted Beta",
                    "status": "accepted",
                }],
                "diagnostics": {
                    "raw_evidence_count": 1,
                    "active_evidence_count": 1,
                    "relation_status_counts": {"accepted": 1},
                    "canonicalization": {
                        "canonical_entities": [
                            {
                                "canonical_id": "ent_persisted_alpha",
                                "chunk_uids": ["c1"],
                            },
                            {
                                "canonical_id": "ent_not_retrieved",
                                "chunk_uids": ["other-chunk"],
                            },
                        ],
                    },
                    "entity_support": {
                        "elements": [
                            {
                                "canonical_id": "ent_persisted_alpha",
                                "query_protected": False,
                            },
                            {
                                "canonical_id": "ent_not_retrieved",
                                "query_protected": False,
                            },
                        ],
                        "query_protected": [],
                    },
                    "relation_recovery": {
                        "candidate_generation": {
                            "generated": [{"head": "Persisted Alpha", "tail": "Persisted Beta"}],
                            "deduplicated": [],
                            "budget_rejected": [],
                        },
                        "verification": [{
                            "status": "accepted",
                            "attempted": True,
                            "provider": "persisted-provider",
                        }],
                        "cleanup": {
                            "removed_entity_ids": [],
                            "preserved": [{
                                "canonical_id": "ent_persisted_alpha",
                                "reason": "query_protected",
                            }],
                        },
                        "counts": {
                            "local": 1,
                            "cross_chunk": 1,
                            "accepted": 1,
                            "rejected": 0,
                            "unverified": 0,
                        },
                    },
                },
            },
        },
    }
    persisted_diagnostics_before = deepcopy(persisted_diagnostics)

    def persistent_graph_view(collection, chunks, object_store=None):
        del collection, chunks, object_store
        return nx.Graph(), [[1]], {}, 0.0, persisted_diagnostics

    feedback_decisions[:] = [
        {
            "final_decision": "retry retrieval",
            "stop": False,
            "next_stage": "retrieval",
            "updated_retry_state": {
                "retrieval_retries": 1,
                "prompt_retries": 0,
                "reduce_retries": 0,
                "total_retries": 1,
            },
        },
        {"final_decision": "stop"},
    ]
    monkeypatch.setattr("launcher.runners._persistent_graph_view", persistent_graph_view)
    run_full_pipeline({
        "mode": "full-pipeline",
        "profile": "local",
        "collection": "test",
        "query": "test",
        "retrieval_limit": 5,
        "pdf_path": "",
        "json_output": "",
        "artifact_dir": str(persistent_dir),
        "enable_graph_artifact": True,
        "verbose": True,
    })

    assert received_sessions == [
        ("summarizer", shared_session),
        ("reducer", shared_session),
        ("summarizer", shared_session),
        ("reducer", shared_session),
    ]
    assert received_extractor_session == [shared_session, shared_session]
    for current_dir in (persistent_dir, persistent_dir / "attempt-1"):
        assert json.loads((current_dir / "relation_evidence.json").read_text()) == {
            "documents": {
                "persisted-document": {
                    "raw_evidence": persisted_diagnostics["documents"]["persisted-document"]["raw_evidence"],
                    "active_evidence": persisted_diagnostics["documents"]["persisted-document"]["active_evidence"],
                    "counts": {
                        "raw_evidence_count": 1,
                        "active_evidence_count": 1,
                        "relation_status_counts": {"accepted": 1},
                    },
                },
            },
        }
        assert json.loads((current_dir / "entity_canonicalization.json").read_text()) == {
            "documents": {
                "persisted-document": {
                    "canonical_entities": [
                        {
                            "canonical_id": "ent_persisted_alpha",
                            "chunk_uids": ["c1"],
                        },
                        {
                            "canonical_id": "ent_not_retrieved",
                            "chunk_uids": ["other-chunk"],
                        },
                    ],
                },
            },
        }
        assert json.loads((current_dir / "orphan_node_report.json").read_text()) == {
            "documents": {
                "persisted-document": {
                    "elements": [
                        {
                            "canonical_id": "ent_persisted_alpha",
                            "query_protected": True,
                        },
                        {
                            "canonical_id": "ent_not_retrieved",
                            "query_protected": False,
                        },
                    ],
                    "query_protected": ["ent_persisted_alpha"],
                },
            },
        }
        assert json.loads((current_dir / "relation_recovery.json").read_text()) == {
            "documents": {
                "persisted-document": persisted_diagnostics_before["documents"][
                    "persisted-document"
                ]["diagnostics"]["relation_recovery"],
            },
        }
    assert persisted_diagnostics == persisted_diagnostics_before
    assert persisted_diagnostics["documents"]["persisted-document"]["diagnostics"]["entity_support"] == {
        "elements": [
            {"canonical_id": "ent_persisted_alpha", "query_protected": False},
            {"canonical_id": "ent_not_retrieved", "query_protected": False},
        ],
        "query_protected": [],
    }
