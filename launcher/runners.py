# ============================================================
# MODE RUNNERS
# Execute a single Launcher Mode with resolved config.
# ============================================================

import json
import os
from datetime import datetime, timezone


def _print_stage(stage_number: int, total_stages: int, title: str, verbose: bool = False, details=None) -> None:
    print(f"\nStage {stage_number}/{total_stages}: {title}")
    if not verbose:
        return
    if details is None:
        return
    if isinstance(details, str):
        details = [details]
    for detail in details:
        print(f"  {detail}")


def _artifact_path(artifact_dir: str, filename: str) -> str:
    return os.path.join(artifact_dir, filename)


def run_query_only(config: dict) -> None:
    """Execute a Query-Only Run: retrieve ranked chunks without the full pipeline."""
    from embedding.embedder import TextEmbedder
    from vectordb.qdrant_handler import QdrantHandler

    collection = config["collection"]
    query = config["query"]
    retrieval_limit = config["retrieval_limit"]
    json_output = config.get("json_output", "")
    verbose = bool(config.get("verbose", False))

    print("\n=== QUERY-ONLY RUN ===")
    print(f"  Collection : {collection}")
    print(f"  Query      : {query}")
    print(f"  Limit      : {retrieval_limit}")

    _print_stage(1, 3, "embed query", verbose, [
        f"Collection target: {collection}",
        f"JSON artifact: {json_output or '(disabled)'}",
    ])
    qdrant = QdrantHandler(collection_name=collection)
    embedder = TextEmbedder()
    query_vector = embedder.embed_text(query)

    _print_stage(2, 3, "retrieve chunks", verbose, f"Retrieval limit: {retrieval_limit}")
    chunks = qdrant.search_as_chunks(query_vector, limit=retrieval_limit)

    print(f"\n  Retrieved chunks: {len(chunks)}")

    _print_stage(3, 3, "emit output", verbose, f"Chunk count: {len(chunks)}")
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
    verbose = bool(config.get("verbose", False))

    print("\n=== INGEST RUN ===")
    print(f"  PDF        : {pdf_path}")
    print(f"  Collection : {collection}")

    if not os.path.exists(pdf_path):
        raise SystemExit(f"Error: PDF file not found: {pdf_path}")

    _print_stage(1, 4, "load pdf", verbose, f"Source PDF: {pdf_path}")
    loader = DoclingLoader()
    result = loader.process_pdf(pdf_path)
    chunks = result["chunks"]
    if not chunks:
        raise SystemExit("Error: No chunks extracted from the PDF.")

    _print_stage(2, 4, "embed chunks", verbose, f"Chunk count: {len(chunks)}")
    embedder = TextEmbedder()
    vectors = embedder.embed_chunks(chunks)

    _print_stage(3, 4, "ensure collection", verbose, f"Collection target: {collection}")
    qdrant = QdrantHandler(collection_name=collection)
    qdrant.create_collection_if_not_exists(vector_size=len(vectors[0]))

    _print_stage(4, 4, "upload chunks", verbose, [
        f"Chunk count: {len(chunks)}",
        f"Vector size: {len(vectors[0])}",
    ])
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
    from summarizer.provider_router import create_session
    from evaluation.evaluator import SummaryEvaluator
    from evaluation.quality_checker import QualityChecker
    from pipeline.feedback_loop import FeedbackLoopController

    collection = config["collection"]
    query = config["query"]
    retrieval_limit = config["retrieval_limit"]
    pdf_path = config.get("pdf_path", "")
    artifact_dir = config.get("artifact_dir", "") or "output"
    verbose = bool(config.get("verbose", False))

    print("\n=== FULL-PIPELINE RUN ===")
    print(f"  Collection : {collection}")
    print(f"  Query      : {query}")
    print(f"  Limit      : {retrieval_limit}")
    print(f"  Artifacts  : {artifact_dir}")

    retry_state = {
        "retrieval_retries": 0,
        "prompt_retries": 0,
        "reduce_retries": 0,
        "total_retries": 0,
    }

    _print_stage(1, 8, "retrieve chunks", verbose, [
        f"Collection target: {collection}",
        f"Artifact directory: {artifact_dir}",
        f"Retrieval limit: {retrieval_limit}",
    ])
    embedder = TextEmbedder()
    qdrant = QdrantHandler(collection_name=collection)

    query_vector = embedder.embed_text(query)
    retrieved_chunks = qdrant.search_as_chunks(query_vector, limit=retrieval_limit)

    print(f"\n  Retrieved chunks: {len(retrieved_chunks)}")

    retrieved_chunks = _maybe_render_images(retrieved_chunks, pdf_path)

    _print_stage(2, 8, "extract entities and relations", verbose, f"Chunk count: {len(retrieved_chunks)}")
    extractor = EntityExtractor()
    entity_map, all_entities = extractor.extract_entities(retrieved_chunks)
    all_relations = []
    for chunk in retrieved_chunks:
        rels = extractor.extract_relations_llm(
            chunk["text"],
            entity_map.get(chunk["chunk_id"], []),
        )
        all_relations.extend(rels)

    _print_stage(3, 8, "build graph", verbose, [
        f"Entities: {len(all_entities)}",
        f"Relations: {len(all_relations)}",
    ])
    graph_builder = GraphBuilder()
    chunk_embeddings = [embedder.embed_text(c["text"]) for c in retrieved_chunks]
    G = graph_builder.build_graph(retrieved_chunks, chunk_embeddings, all_entities, all_relations)

    _print_stage(4, 8, "detect communities", verbose)
    detector = CommunityDetector()
    G, communities, community_map, modularity = detector.detect(G)

    _print_stage(5, 8, "rank graph and prune context", verbose, [
        f"Communities: {len(communities)}",
        f"Modularity: {modularity:.4f}",
    ])
    analyzer = GraphAnalyzer()
    ranked = analyzer.analyze(G)
    csv_path = analyzer.save_ranked_csv(ranked, _artifact_path(artifact_dir, "graph_ranked_nodes.csv"))
    json_path = analyzer.save_ranked_json(ranked, _artifact_path(artifact_dir, "graph_ranked_nodes.json"))
    summary_path = analyzer.save_summary_json(ranked, communities, modularity, _artifact_path(artifact_dir, "graph_summary.json"))

    print(f"\n  Communities : {len(communities)}")
    print(f"  Modularity  : {modularity:.4f}")

    pruner = SummaryPruner(top_k_per_community=3, top_k_global=10)
    pruned_result = pruner.select_top_chunks(ranked, retrieved_chunks)
    pruned_json = pruner.save_pruned_json(pruned_result, _artifact_path(artifact_dir, "pruned_summary_context.json"))
    pruned_csv = pruner.save_pruned_csv(pruned_result, _artifact_path(artifact_dir, "pruned_summary_context.csv"))

    _print_stage(6, 8, "summarize communities", verbose)
    prompt_builder = PromptBuilder(max_chars_per_chunk=1200)
    community_prompts = prompt_builder.build_all_community_prompts(pruned_result, query=query, style="concise")

    session = create_session()
    if verbose:
        resolved_chain = session.resolve_chain() if hasattr(session, "resolve_chain") else []
        if resolved_chain:
            print(f"  Resolved providers: {', '.join(resolved_chain)}")
    summarizer = LLMSummarizer(session=session)
    community_summaries = summarizer.summarize_communities(community_prompts)
    map_json = summarizer.save_map_summaries_json(community_summaries, _artifact_path(artifact_dir, "community_map_summaries.json"))
    map_txt = summarizer.save_map_summaries_txt(community_summaries, _artifact_path(artifact_dir, "community_map_summaries.txt"))

    _print_stage(7, 8, "reduce final summary", verbose, f"Community summaries: {len(community_summaries)}")
    reducer = HierarchicalReducer(session=session)
    final_result = reducer.reduce_summaries(community_summaries, query=query, style="concise")
    final_json = reducer.save_final_summary_json(final_result, _artifact_path(artifact_dir, "final_summary.json"))
    final_txt = reducer.save_final_summary_txt(final_result, _artifact_path(artifact_dir, "final_summary.txt"))

    print("\n  Final Summary:")
    print(f"  {final_result['final_summary'][:200]}...")

    _print_stage(8, 8, "evaluate quality and decide", verbose)
    evaluator = SummaryEvaluator()
    eval_result = evaluator.evaluate_without_reference(
        generated_summary=final_result["final_summary"],
        source_chunks=retrieved_chunks,
    )
    evaluation_path = evaluator.save_evaluation_json(eval_result, _artifact_path(artifact_dir, "evaluation_result.json"))

    checker = QualityChecker()
    quality_result = checker.check(eval_result)
    action_result = checker.suggest_action(quality_result)
    report_path = checker.save_quality_report(quality_result, action_result, _artifact_path(artifact_dir, "quality_gate_report.json"))

    print(f"\n  Quality Status  : {quality_result['status']}")
    print(f"  Suggested Action: {action_result['action']}")

    controller = FeedbackLoopController(max_retries=2)
    decision = controller.decide(
        quality_result=quality_result,
        action_result=action_result,
        retry_state=retry_state,
    )
    decision_path = controller.save_decision(decision, _artifact_path(artifact_dir, "feedback_loop_decision.json"))

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
