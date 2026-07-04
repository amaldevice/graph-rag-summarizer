# ============================================================
# RETRIEVAL + SUMMARIZATION
# Qdrant -> Retrieval -> Graph -> Summary -> Evaluation
# ============================================================

from dotenv import load_dotenv
load_dotenv()

import os

from config import settings
from preprocessing.docling_loader import DoclingLoader
from embedding.embedder import TextEmbedder
from vectordb.qdrant_handler import QdrantHandler
from graph.entity_extractor import EntityExtractor
from graph.graph_builder import GraphBuilder
from graph.community_detector import CommunityDetector
from graph.graph_analyzer import GraphAnalyzer
from summarizer.pruner import SummaryPruner
from summarizer.prompt_builder import PromptBuilder
from summarizer.llm_summarizer import LLMSummarizer
from summarizer.hierarchical_reducer import HierarchicalReducer
from evaluation.evaluator import SummaryEvaluator
from evaluation.quality_checker import QualityChecker
from pipeline.feedback_loop import FeedbackLoopController


def collect_pages_from_chunks(chunks: list) -> list:
    pages = []
    for chunk in chunks:
        page_no = chunk.get("page_no")
        if isinstance(page_no, int):
            pages.append(page_no)
    return sorted(set(pages))


def attach_image_urls_to_retrieved_chunks(retrieved_chunks: list, page_image_map: dict) -> list:
    for chunk in retrieved_chunks:
        page_no = chunk.get("page_no")
        if page_no in page_image_map:
            chunk["image_url"] = page_image_map[page_no]
    return retrieved_chunks


def maybe_render_images_on_demand(retrieved_chunks: list):
    if not settings.ENABLE_ON_DEMAND_PAGE_RENDER:
        print("ℹ️ On-demand page render nonaktif.")
        return retrieved_chunks

    pdf_path = os.getenv("PDF_PATH", "")
    if not pdf_path:
        print("ℹ️ PDF_PATH tidak diisi, skip on-demand render.")
        print("   Retrieval tetap jalan langsung dari Qdrant.")
        return retrieved_chunks

    loader = DoclingLoader()
    target_pages = collect_pages_from_chunks(retrieved_chunks)
    print(f"Target pages for on-demand render: {target_pages}")

    uploaded_images = loader.render_and_upload_pages_on_demand(
        pdf_path=pdf_path,
        target_pages=target_pages,
    )
    page_image_map = loader.build_page_image_map(uploaded_images)
    retrieved_chunks = attach_image_urls_to_retrieved_chunks(retrieved_chunks, page_image_map)

    print(f"On-demand images uploaded : {len(uploaded_images)}")
    print(f"Unique pages rendered     : {len(page_image_map)}")
    return retrieved_chunks


def main():
    query = os.getenv("QUERY_TEXT", "What is the main idea of the paper?")
    retrieval_limit = int(os.getenv("RETRIEVAL_LIMIT", 10))

    retry_state = {
        "retrieval_retries": 0,
        "prompt_retries": 0,
        "reduce_retries": 0,
        "total_retries": 0,
    }

    print("\n=== RETRIEVAL MODE ===")
    print(f"QUERY_TEXT      : {query}")
    print(f"RETRIEVAL_LIMIT : {retrieval_limit}")

    # 1. Query embedding + retrieval
    embedder = TextEmbedder()
    qdrant = QdrantHandler()

    query_vector = embedder.embed_text(query)
    retrieved_chunks = qdrant.search_as_chunks(query_vector, limit=retrieval_limit)

    print("\n=== RETRIEVAL DONE ===")
    print(f"Retrieved chunks : {len(retrieved_chunks)}")

    retrieved_chunks = maybe_render_images_on_demand(retrieved_chunks)

    # 2. Entity Extraction
    extractor = EntityExtractor()
    entity_map, all_entities = extractor.extract_entities(retrieved_chunks)

    all_relations = []
    for chunk in retrieved_chunks:
        rels = extractor.extract_relations_llm(
            chunk["text"],
            entity_map.get(chunk["chunk_id"], [])
        )
        all_relations.extend(rels)

    # 3. Graph Construction
    graph_builder = GraphBuilder()
    chunk_embeddings = [embedder.embed_text(c["text"]) for c in retrieved_chunks]
    G = graph_builder.build_graph(
        retrieved_chunks,
        chunk_embeddings,
        all_entities,
        all_relations,
    )

    # 4. Community Detection
    detector = CommunityDetector()
    G, communities, community_map, modularity = detector.detect(G)

    # 5. Graph Analysis
    analyzer = GraphAnalyzer()
    ranked = analyzer.analyze(G)

    csv_path = analyzer.save_ranked_csv(ranked)
    json_path = analyzer.save_ranked_json(ranked)
    summary_path = analyzer.save_summary_json(ranked, communities, modularity)

    print("\n=== GRAPH PIPELINE DONE ===")
    print(f"Communities : {len(communities)}")
    print(f"Modularity  : {modularity:.4f}")
    print(f"CSV saved   : {csv_path}")
    print(f"JSON saved  : {json_path}")
    print(f"Summary     : {summary_path}")
    print("\nTop 10 Ranked Nodes:")
    print(ranked.head(10).to_string(index=False))

    # 6. Pruning
    pruner = SummaryPruner(top_k_per_community=3, top_k_global=10)
    pruned_result = pruner.select_top_chunks(ranked, retrieved_chunks)

    pruned_json = pruner.save_pruned_json(pruned_result)
    pruned_csv = pruner.save_pruned_csv(pruned_result)

    print("\n=== PRUNING DONE ===")
    print(f"Pruned JSON : {pruned_json}")
    print(f"Pruned CSV  : {pruned_csv}")
    print(f"Communities with selected chunks: {len(pruned_result['communities'])}")

    # 7. Prompt Builder
    prompt_builder = PromptBuilder(max_chars_per_chunk=1200)
    community_prompts = prompt_builder.build_all_community_prompts(
        pruned_result,
        query=query,
        style="concise",
    )

    # 8. Map Summarization
    summarizer = LLMSummarizer()
    community_summaries = summarizer.summarize_communities(community_prompts)

    map_json = summarizer.save_map_summaries_json(community_summaries)
    map_txt = summarizer.save_map_summaries_txt(community_summaries)

    print("\n=== MAP SUMMARIZATION DONE ===")
    print(f"Map JSON : {map_json}")
    print(f"Map TXT  : {map_txt}")

    # 9. Hierarchical Reduce
    reducer = HierarchicalReducer()
    final_result = reducer.reduce_summaries(
        community_summaries,
        query=query,
        style="concise",
    )

    final_json = reducer.save_final_summary_json(final_result)
    final_txt = reducer.save_final_summary_txt(final_result)

    print("\n=== FINAL SUMMARY DONE ===")
    print(f"Final JSON : {final_json}")
    print(f"Final TXT  : {final_txt}")
    print("\nFinal Summary:")
    print(final_result["final_summary"])

    # 10. Evaluation
    evaluator = SummaryEvaluator()
    eval_result = evaluator.evaluate_without_reference(
        generated_summary=final_result["final_summary"],
        source_chunks=retrieved_chunks,
    )
    evaluation_path = evaluator.save_evaluation_json(eval_result)

    # 11. Quality Check
    checker = QualityChecker()
    quality_result = checker.check(eval_result)
    action_result = checker.suggest_action(quality_result)
    report_path = checker.save_quality_report(quality_result, action_result)

    print("\n=== QUALITY CHECK DONE ===")
    print(f"Evaluation JSON : {evaluation_path}")
    print(f"Quality Report  : {report_path}")
    print(f"Quality Status  : {quality_result['status']}")
    print(f"Suggested Action: {action_result['action']}")

    # 12. Feedback Loop Decision
    controller = FeedbackLoopController(max_retries=2)
    decision = controller.decide(
        quality_result=quality_result,
        action_result=action_result,
        retry_state=retry_state,
    )
    decision_path = controller.save_decision(decision)

    print("\n=== FEEDBACK LOOP DECISION ===")
    print(f"Decision JSON : {decision_path}")
    print(f"Stop          : {decision['stop']}")
    print(f"Next Stage    : {decision['next_stage']}")
    print(f"Decision      : {decision['final_decision']}")
    print(f"Message       : {decision['message']}")


if __name__ == "__main__":
    main()
