import sys
import types
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import settings


def test_full_pipeline_uses_one_provider_session_for_summarizer_and_reducer(monkeypatch):
    shared_session = object()
    received_sessions = []
    saved_paths = {}

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

        def search_as_chunks(self, query_vector, limit: int):
            del query_vector, limit
            return [{"chunk_id": "c1", "text": "chunk text", "page_no": 1}]

    class FakeEntityExtractor:
        def extract_entities(self, chunks):
            del chunks
            return {"c1": []}, []

        def extract_relations_llm(self, text, entities):
            del text, entities
            return []

    class FakeGraphBuilder:
        def build_graph(self, retrieved_chunks, chunk_embeddings, all_entities, all_relations):
            del retrieved_chunks, chunk_embeddings, all_entities, all_relations
            return object()

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

        def save_summary_json(self, ranked, communities, modularity, output_path="output/graph_summary.json"):
            del ranked, communities, modularity
            saved_paths["graph_summary_json"] = output_path
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
            return {"final_decision": "stop"}

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

    run_full_pipeline({
        "mode": "full-pipeline",
        "profile": "local",
        "collection": "test",
        "query": "test",
        "retrieval_limit": 5,
        "pdf_path": "",
        "json_output": "",
        "artifact_dir": "output/run-1",
        "verbose": True,
    })

    assert received_sessions == [
        ("summarizer", shared_session),
        ("reducer", shared_session),
    ]
    assert saved_paths["graph_ranked_csv"] == "output/run-1/graph_ranked_nodes.csv"
    assert saved_paths["graph_ranked_json"] == "output/run-1/graph_ranked_nodes.json"
    assert saved_paths["graph_summary_json"] == "output/run-1/graph_summary.json"
    assert saved_paths["pruned_json"] == "output/run-1/pruned_summary_context.json"
    assert saved_paths["pruned_csv"] == "output/run-1/pruned_summary_context.csv"
    assert saved_paths["map_json"] == "output/run-1/community_map_summaries.json"
    assert saved_paths["map_txt"] == "output/run-1/community_map_summaries.txt"
    assert saved_paths["final_json"] == "output/run-1/final_summary.json"
    assert saved_paths["final_txt"] == "output/run-1/final_summary.txt"
    assert saved_paths["evaluation_json"] == "output/run-1/evaluation_result.json"
    assert saved_paths["quality_json"] == "output/run-1/quality_gate_report.json"
    assert saved_paths["decision_json"] == "output/run-1/feedback_loop_decision.json"
