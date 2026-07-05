# ============================================================
# MODE RUNNERS
# Execute a single Launcher Mode with resolved config.
# ============================================================

import json
import os
from datetime import datetime, timezone


def run_query_only(config: dict) -> None:
    """Execute a Query-Only Run: retrieve ranked chunks without the full pipeline."""
    from embedding.embedder import TextEmbedder
    from vectordb.qdrant_handler import QdrantHandler

    from config import settings

    collection = config["collection"]
    query = config["query"]
    retrieval_limit = config["retrieval_limit"]
    json_output = config.get("json_output", "")

    print("\n=== QUERY-ONLY RUN ===")
    print(f"  Collection : {collection}")
    print(f"  Query      : {query}")
    print(f"  Limit      : {retrieval_limit}")

    qdrant = QdrantHandler(collection_name=collection)
    embedder = TextEmbedder()

    query_vector = embedder.embed_text(query)
    chunks = qdrant.search_as_chunks(query_vector, limit=retrieval_limit)

    print(f"\n  Retrieved chunks: {len(chunks)}")

    if not chunks:
        print("  No chunks found for this query.")
        return

    print("\n--- Chunk Results ---")
    for chunk in chunks:
        rank = chunk.get("rank", "?")
        score = chunk.get("score", "")
        page = chunk.get("page_no", "")
        text_preview = (chunk.get("text") or "")[:120].replace("\n", " ")
        print(f"  [{rank}] score={score} page={page}")
        print(f"      {text_preview}...")
    print("--- End Results ---")

    if json_output:
        output_dir = os.path.dirname(json_output)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        artifact = {
            "mode": "query-only",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "collection": collection,
            "query": query,
            "retrieval_limit": retrieval_limit,
            "chunk_count": len(chunks),
            "chunks": chunks,
        }
        with open(json_output, "w") as f:
            json.dump(artifact, f, indent=2, default=str)
        print(f"\n  JSON artifact saved: {json_output}")


def run_ingest(config: dict) -> None:
    """Execute an Ingest Run: PDF -> chunk -> embed -> Qdrant."""
    from preprocessing.docling_loader import DoclingLoader
    from embedding.embedder import TextEmbedder
    from vectordb.qdrant_handler import QdrantHandler

    pdf_path = config["pdf_path"]
    collection = config["collection"]

    print("\n=== INGEST RUN ===")
    print(f"  PDF        : {pdf_path}")
    print(f"  Collection : {collection}")

    if not os.path.exists(pdf_path):
        raise SystemExit(f"Error: PDF file not found: {pdf_path}")

    loader = DoclingLoader()
    result = loader.process_pdf(pdf_path)
    chunks = result["chunks"]
    if not chunks:
        raise SystemExit("Error: No chunks extracted from the PDF.")

    embedder = TextEmbedder()
    vectors = embedder.embed_chunks(chunks)

    qdrant = QdrantHandler(collection_name=collection)
    qdrant.create_collection_if_not_exists(vector_size=len(vectors[0]))
    qdrant.upsert_chunks(chunks, vectors)

    print(f"\n  Total chunks uploaded : {len(chunks)}")
    print(f"  Collection            : {collection}")
    print("  Ingest complete.")


def run_full_pipeline(config: dict) -> None:
    """Execute a Full-Pipeline Run: retrieve -> graph -> summarize -> evaluate."""
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
    from preprocessing.docling_loader import DoclingLoader

    from config import settings

    collection = config["collection"]
    query = config["query"]
    retrieval_limit = config["retrieval_limit"]
    pdf_path = config.get("pdf_path", "")

    print("\n=== FULL-PIPELINE RUN ===")
    print(f"  Collection : {collection}")
    print(f"  Query      : {query}")
    print(f"  Limit      : {retrieval_limit}")

    retry_state = {
        "retrieval_retries": 0,
        "prompt_retries": 0,
        "reduce_retries": 0,
        "total_retries": 0,
    }

    embedder = TextEmbedder()
    qdrant = QdrantHandler(collection_name=collection)

    query_vector = embedder.embed_text(query)
    retrieved_chunks = qdrant.search_as_chunks(query_vector, limit=retrieval_limit)

    print(f"\n  Retrieved chunks: {len(retrieved_chunks)}")

    retrieved_chunks = _maybe_render_images(retrieved_chunks, pdf_path)

    extractor = EntityExtractor()
    entity_map, all_entities = extractor.extract_entities(retrieved_chunks)
    all_relations = []
    for chunk in retrieved_chunks:
        rels = extractor.extract_relations_llm(
            chunk["text"],
            entity_map.get(chunk["chunk_id"], []),
        )
        all_relations.extend(rels)

    graph_builder = GraphBuilder()
    chunk_embeddings = [embedder.embed_text(c["text"]) for c in retrieved_chunks]
    G = graph_builder.build_graph(retrieved_chunks, chunk_embeddings, all_entities, all_relations)

    detector = CommunityDetector()
    G, communities, community_map, modularity = detector.detect(G)

    analyzer = GraphAnalyzer()
    ranked = analyzer.analyze(G)
    csv_path = analyzer.save_ranked_csv(ranked)
    json_path = analyzer.save_ranked_json(ranked)
    summary_path = analyzer.save_summary_json(ranked, communities, modularity)

    print(f"\n  Communities : {len(communities)}")
    print(f"  Modularity  : {modularity:.4f}")

    pruner = SummaryPruner(top_k_per_community=3, top_k_global=10)
    pruned_result = pruner.select_top_chunks(ranked, retrieved_chunks)
    pruned_json = pruner.save_pruned_json(pruned_result)
    pruned_csv = pruner.save_pruned_csv(pruned_result)

    prompt_builder = PromptBuilder(max_chars_per_chunk=1200)
    community_prompts = prompt_builder.build_all_community_prompts(pruned_result, query=query, style="concise")

    summarizer = LLMSummarizer()
    community_summaries = summarizer.summarize_communities(community_prompts)
    map_json = summarizer.save_map_summaries_json(community_summaries)
    map_txt = summarizer.save_map_summaries_txt(community_summaries)

    reducer = HierarchicalReducer()
    final_result = reducer.reduce_summaries(community_summaries, query=query, style="concise")
    final_json = reducer.save_final_summary_json(final_result)
    final_txt = reducer.save_final_summary_txt(final_result)

    print("\n  Final Summary:")
    print(f"  {final_result['final_summary'][:200]}...")

    evaluator = SummaryEvaluator()
    eval_result = evaluator.evaluate_without_reference(
        generated_summary=final_result["final_summary"],
        source_chunks=retrieved_chunks,
    )
    evaluation_path = evaluator.save_evaluation_json(eval_result)

    checker = QualityChecker()
    quality_result = checker.check(eval_result)
    action_result = checker.suggest_action(quality_result)
    report_path = checker.save_quality_report(quality_result, action_result)

    print(f"\n  Quality Status  : {quality_result['status']}")
    print(f"  Suggested Action: {action_result['action']}")

    controller = FeedbackLoopController(max_retries=2)
    decision = controller.decide(
        quality_result=quality_result,
        action_result=action_result,
        retry_state=retry_state,
    )
    decision_path = controller.save_decision(decision)

    print(f"\n  Decision: {decision['final_decision']}")


def _maybe_render_images(retrieved_chunks: list, pdf_path: str) -> list:
    """Optionally render page images if on-demand mode is enabled and PDF is available."""
    from config import settings

    if not settings.ENABLE_ON_DEMAND_PAGE_RENDER:
        return retrieved_chunks
    if not pdf_path:
        return retrieved_chunks

    from preprocessing.docling_loader import DoclingLoader

    loader = DoclingLoader()
    target_pages = sorted({
        c.get("page_no")
        for c in retrieved_chunks
        if isinstance(c.get("page_no"), int)
    })
    if not target_pages:
        return retrieved_chunks

    uploaded = loader.render_and_upload_pages_on_demand(pdf_path=pdf_path, target_pages=target_pages)
    page_image_map = loader.build_page_image_map(uploaded)
    for chunk in retrieved_chunks:
        page_no = chunk.get("page_no")
        if page_no in page_image_map:
            chunk["image_url"] = page_image_map[page_no]

    print(f"  On-demand images uploaded: {len(uploaded)}")
    return retrieved_chunks
