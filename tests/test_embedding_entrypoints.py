import importlib
import sys
import types
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import settings


def _load_module_with_stubs(module_name: str, monkeypatch, stubs: dict[str, types.ModuleType]):
    sys.modules.pop(module_name, None)
    for stub_name, stub_module in stubs.items():
        monkeypatch.setitem(sys.modules, stub_name, stub_module)
    module = importlib.import_module(module_name)
    return importlib.reload(module)


def test_upload_entrypoint_uses_the_shared_embedding_model_setting(monkeypatch) -> None:
    used_models: list[str] = []
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "shared-model")

    embedder_module = types.ModuleType("embedding.embedder")
    loader_module = types.ModuleType("preprocessing.docling_loader")
    qdrant_module = types.ModuleType("vectordb.qdrant_handler")

    class FakeEmbedder:
        def __init__(self):
            used_models.append(settings.EMBEDDING_MODEL)

        def embed_chunks(self, chunks):
            return [[0.1, 0.2] for _ in chunks]

    class FakeLoader:
        def process_pdf(self, pdf_path: str):
            del pdf_path
            return {"chunks": [{"text": "chunk-1"}]}

    class FakeQdrantHandler:
        def __init__(self, collection_name="test-collection"):
            self.collection_name = collection_name

        def prepare_ingest(self, ingest_mode, document_id, vector_size: int):
            assert ingest_mode == "append"
            assert document_id == "sample"
            assert vector_size == 2

        def upsert_chunks(self, chunks, vectors):
            assert len(chunks) == len(vectors) == 1

    embedder_module.TextEmbedder = FakeEmbedder
    loader_module.DoclingLoader = FakeLoader
    qdrant_module.QdrantHandler = FakeQdrantHandler

    upload_module = _load_module_with_stubs(
        "upload_to_qdrant",
        monkeypatch,
        {
            "embedding.embedder": embedder_module,
            "preprocessing.docling_loader": loader_module,
            "vectordb.qdrant_handler": qdrant_module,
        },
    )
    monkeypatch.setattr(
        "launcher.runners._bind_ingest_collection_mode",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setenv("PDF_PATH", "sample.pdf")
    upload_module.main()

    assert used_models == ["shared-model"]


def test_query_entrypoint_uses_the_shared_embedding_model_setting(monkeypatch) -> None:
    used_models: list[str] = []
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "shared-model")

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
        def __init__(self):
            used_models.append(settings.EMBEDDING_MODEL)

        def embed_text(self, text: str):
            del text
            return [0.1, 0.2]

    class FakeQdrantHandler:
        def __init__(self, collection_name="test"):
            pass

        def revalidate_query_authorization(self):
            pass

        def search_as_chunks(self, query_vector, limit: int):
            del query_vector, limit
            return [{"chunk_id": "c1", "text": "chunk text", "page_no": 1}]

    class FakeDoclingLoader:
        def render_and_upload_pages_on_demand(self, pdf_path: str, target_pages: list[int]):
            del pdf_path, target_pages
            return []

        def build_page_image_map(self, uploaded_images):
            del uploaded_images
            return {}

    class FakeEntityExtractor:
        def __init__(self, provider_router=None):
            del provider_router

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
            return graph, [[]], {}, 0.0

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
            return output_path

        def save_ranked_json(self, ranked, output_path="output/graph_ranked_nodes.json"):
            del ranked
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
            del ranked, communities, modularity, relation_extraction_mode
            return output_path

    class FakeSummaryPruner:
        def __init__(self, top_k_per_community: int, top_k_global: int):
            del top_k_per_community, top_k_global

        def select_top_chunks(self, ranked, retrieved_chunks):
            del ranked, retrieved_chunks
            return {"communities": []}

        def save_pruned_json(self, pruned_result, output_path="output/pruned_summary_context.json"):
            del pruned_result
            return output_path

        def save_pruned_csv(self, pruned_result, output_path="output/pruned_summary_context.csv"):
            del pruned_result
            return output_path

    class FakePromptBuilder:
        def __init__(self, max_chars_per_chunk: int):
            del max_chars_per_chunk

        def build_all_community_prompts(self, pruned_result, query: str, style: str):
            del pruned_result, query, style
            return []

    class FakeSummarizer:
        def __init__(self, session=None):
            del session

        def summarize_communities(self, community_prompts):
            del community_prompts
            return []

        def save_map_summaries_json(self, community_summaries, output_path="output/community_map_summaries.json"):
            del community_summaries
            return output_path

        def save_map_summaries_txt(self, community_summaries, output_path="output/community_map_summaries.txt"):
            del community_summaries
            return output_path

    class FakeReducer:
        def __init__(self, session=None):
            del session

        def reduce_summaries(self, community_summaries, query: str, style: str):
            del community_summaries, query, style
            return {"final_summary": "done"}

        def save_final_summary_json(self, final_result, output_path="output/final_summary.json"):
            del final_result
            return output_path

        def save_final_summary_txt(self, final_result, output_path="output/final_summary.txt"):
            del final_result
            return output_path

    class FakeEvaluator:
        def evaluate_without_reference(self, generated_summary: str, source_chunks):
            del generated_summary, source_chunks
            return {"quality": "ok"}

        def save_evaluation_json(self, eval_result, output_path="output/evaluation_result.json"):
            del eval_result
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
            return output_path

    class FakeFeedbackLoopController:
        def __init__(self, max_retries: int):
            del max_retries

        def decide(self, quality_result, action_result, retry_state):
            del quality_result, action_result, retry_state
            return {
                "decision": "stop",
                "stop": True,
                "reason": "done",
                "retry_state": {},
                "next_stage": "complete",
                "final_decision": "stop",
                "message": "done",
            }

        def save_decision(self, decision, output_path="output/feedback_loop_decision.json"):
            del decision
            return output_path

    embedder_module.TextEmbedder = FakeEmbedder
    qdrant_module.QdrantHandler = FakeQdrantHandler
    docling_module.DoclingLoader = FakeDoclingLoader
    entity_module.EntityExtractor = FakeEntityExtractor
    graph_builder_module.GraphBuilder = FakeGraphBuilder
    community_module.CommunityDetector = FakeCommunityDetector
    analyzer_module.GraphAnalyzer = FakeGraphAnalyzer
    pruner_module.SummaryPruner = FakeSummaryPruner
    prompt_builder_module.PromptBuilder = FakePromptBuilder
    provider_router_module.create_session = lambda: object()
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
    for name, mod in stubs.items():
        monkeypatch.setitem(sys.modules, name, mod)

    monkeypatch.setattr(settings, "ENABLE_ON_DEMAND_PAGE_RENDER", False)

    from launcher.runners import run_full_pipeline

    monkeypatch.setattr("launcher.runners._configure_query_denial", lambda *args: None)

    run_full_pipeline({
        "mode": "full-pipeline",
        "profile": "local",
        "collection": "test",
        "query": "test",
        "retrieval_limit": 5,
        "pdf_path": "",
        "json_output": "",
        "artifact_dir": "output/run-embedding-test",
        "verbose": False,
    })

    assert used_models == ["shared-model"]
