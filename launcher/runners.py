# ============================================================
# MODE RUNNERS
# Execute a single Launcher Mode with resolved config.
# ============================================================

import json
import os
from datetime import datetime, timezone
from pathlib import Path


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


def _stamp_document_identity(chunks: list, document_id: str) -> list:
    from launcher.contract import build_chunk_uid, build_stable_point_id

    for chunk in chunks:
        chunk_id = chunk.get("chunk_id")
        chunk["document_id"] = document_id
        chunk["chunk_uid"] = build_chunk_uid(document_id, chunk_id)
        hierarchy = chunk.get("hierarchy") or {}
        parent_chunk_id = hierarchy.get("parent_chunk_id")
        if parent_chunk_id is not None:
            hierarchy["parent_chunk_uid"] = build_chunk_uid(document_id, parent_chunk_id)
            hierarchy["parent_point_id"] = build_stable_point_id(document_id, parent_chunk_id)
        chunk["hierarchy"] = hierarchy
    return chunks


def _write_json_artifact(path: str, value: dict) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return str(out)


def _build_ingest_graph_artifact(config, collection, document_id, chunks, vectors, ingest_mode):
    """Build the baseline graph after vector upload; vectors survive graph failure."""
    status_path = _artifact_path(config.get("artifact_dir") or "output", "graph_artifact_status.json")
    try:
        from graph.persistent import PersistentGraphPipeline

        pipeline = config.get("graph_pipeline") or PersistentGraphPipeline(
            collection, object_store=config.get("graph_object_store")
        )
        result = pipeline.build_and_publish(
            chunks,
            vectors,
            document_id,
            mode=ingest_mode,
            claim=config.get("graph_claim"),
        )
    except Exception as exc:
        result = {"status": "unavailable", "failure_reason": f"{type(exc).__name__}: {exc}"}
    if config.get("graph_reservation_error") and result.get("status") == "unavailable":
        result["failure_reason"] = config["graph_reservation_error"]
    _write_json_artifact(status_path, {
        "collection": collection,
        "document_id": document_id,
        "ingest_mode": ingest_mode,
        "status": result.get("status", "unavailable"),
        "artifact_key": result.get("artifact_key"),
        "artifact_digest": result.get("artifact_digest"),
        "failure_reason": result.get("failure_reason"),
        "counts": (result.get("details") or {}).get("diagnostics", {}),
    })
    return result


def _persistent_graph_view(collection, chunks, object_store=None):
    """Load namespaced persisted document graphs; return None for compatibility fallback."""
    from graph.persistent import PersistentGraphReader, default_graph_services
    import networkx as nx

    document_ids = sorted({chunk.get("document_id") for chunk in chunks if chunk.get("document_id")})
    if not document_ids:
        return None
    manifests, artifacts = default_graph_services(collection, object_store)
    reader = PersistentGraphReader(manifests, artifacts)
    merged = nx.Graph()
    found = False
    for document_id in document_ids:
        document_chunks = [chunk for chunk in chunks if chunk.get("document_id") == document_id]
        if not manifests.preflight(document_id)["allowed"]:
            for chunk in document_chunks:
                chunk["graph_denied"] = True
            continue
        graph = reader.load(document_id, document_chunks)
        if graph is None:
            continue
        found = True
        mapping = {}
        for node, attrs in graph.nodes(data=True):
            if attrs.get("type") == "chunk":
                local_index = next((i for i, chunk in enumerate(chunks) if chunk.get("chunk_uid") == attrs.get("chunk_uid")), None)
                if local_index is not None:
                    mapping[node] = f"chunk_{local_index}"
            else:
                mapping[node] = f"{document_id}::{node}"
        merged = nx.compose(merged, nx.relabel_nodes(graph, mapping, copy=True))
    if not found:
        return None
    communities = {}
    community_map = {}
    for node, attrs in merged.nodes(data=True):
        community = attrs.get("community", -1)
        community_map[node] = community
        communities.setdefault(community, []).append(node)
    return merged, communities, community_map, float(merged.graph.get("modularity", 0.0))


def _configure_query_denial(qdrant, collection, object_store=None):
    from graph.persistent import default_graph_services

    manifests, _ = default_graph_services(collection, object_store)
    snapshot = manifests.read_snapshot()
    if (
        snapshot.manifest.get("pending_tombstone_set_digest") is not None
        or snapshot.manifest.get("collection_operation_id") is not None
    ):
        raise RuntimeError("tombstone proof is pending; query denied")
    manifests_tombstones = manifests.tombstone_controls(snapshot.manifest)
    qdrant.verify_tombstone_control_points(
        manifests_tombstones,
        expected_digest=snapshot.manifest.get("tombstone_set_digest"),
    )
    if not manifests.revalidate(snapshot):
        raise RuntimeError("manifest changed during tombstone preflight")
    denied = [
        document_id
        for document_id, entry in snapshot.manifest.get("documents", {}).items()
        if entry.get("status") == "tombstoned"
    ]
    qdrant.set_denied_document_ids(denied)
    qdrant.set_active_vector_generations({
        document_id: entry["document_generation"]
        for document_id, entry in snapshot.manifest.get("documents", {}).items()
        if entry.get("status") != "tombstoned" and entry.get("document_generation") is not None
    }, {
        document_id: entry["document_attempt_id"]
        for document_id, entry in snapshot.manifest.get("documents", {}).items()
        if entry.get("status") != "tombstoned" and entry.get("document_attempt_id") is not None
    })


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
    if config.get("enable_graph_artifact", False):
        _configure_query_denial(qdrant, collection, config.get("graph_object_store"))
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
    """Execute an Ingest Run with document-safe collection lifecycle handling."""
    from launcher.contract import (
        DEFAULT_INGEST_MODE,
        resolve_ingest_mode,
        suggest_document_id_from_pdf,
    )
    from preprocessing.docling_loader import DoclingLoader
    from embedding.embedder import TextEmbedder
    from vectordb.qdrant_handler import QdrantHandler

    pdf_path = config["pdf_path"]
    collection = config["collection"]
    verbose = bool(config.get("verbose", False))
    ingest_mode = resolve_ingest_mode(config.get("ingest_mode", DEFAULT_INGEST_MODE))
    document_id = (config.get("document_id") or suggest_document_id_from_pdf(pdf_path)).strip()
    if not document_id:
        raise SystemExit("Error: document_id cannot be empty")

    print("\n=== INGEST RUN ===")
    print(f"  PDF        : {pdf_path}")
    print(f"  Collection : {collection}")
    print(f"  Ingest Mode: {ingest_mode}")
    print(f"  Document ID: {document_id}")

    if not os.path.exists(pdf_path):
        raise SystemExit(f"Error: PDF file not found: {pdf_path}")

    _print_stage(1, 4, "load pdf", verbose, f"Source PDF: {pdf_path}")
    loader = DoclingLoader()
    result = loader.process_pdf(pdf_path)
    chunks = result["chunks"]
    if not chunks:
        raise SystemExit("Error: No chunks extracted from the PDF.")
    _stamp_document_identity(chunks, document_id)

    _print_stage(2, 4, "embed chunks", verbose, f"Chunk count: {len(chunks)}")
    embedder = TextEmbedder()
    vectors = embedder.embed_chunks(chunks)

    graph_pipeline = None
    graph_claim = None
    collection_tombstone_manifest = None
    if config.get("enable_graph_artifact", False):
        try:
            from graph.persistent import PersistentGraphPipeline

            graph_pipeline = PersistentGraphPipeline(
                collection, object_store=config.get("graph_object_store")
            )
            config["graph_pipeline"] = graph_pipeline
            if ingest_mode != "replace-collection":
                graph_claim = graph_pipeline.reserve(chunks, document_id, mode=ingest_mode)
                config["graph_claim"] = graph_claim
        except Exception as exc:
            raise RuntimeError(f"persistent graph reservation failed: {type(exc).__name__}: {exc}") from exc

    _print_stage(3, 4, "prepare collection", verbose, [
        f"Collection target: {collection}",
        f"Operation: {ingest_mode}",
        f"Document ID: {document_id}",
    ])
    qdrant = QdrantHandler(collection_name=collection)
    if graph_pipeline and ingest_mode == "replace-collection":
        collection_operation_id = f"replace-collection:{collection}:{document_id}"
        collection_tombstone_manifest = graph_pipeline.manifests.tombstone_documents(
            {document_id}, collection_operation_id
        )
        qdrant.set_collection_claim(
            graph_pipeline.manifests,
            collection_operation_id,
            collection_tombstone_manifest["collection_fence_token"],
        )
    if graph_pipeline and graph_claim:
        qdrant.set_graph_claim(graph_pipeline.manifests, graph_claim)
    try:
        qdrant.prepare_ingest(
            ingest_mode=ingest_mode,
            document_id=document_id,
            vector_size=len(vectors[0]),
        )
        if graph_pipeline and collection_tombstone_manifest:
            tombstoned_entries = [
                entry for entry in collection_tombstone_manifest.get("documents", {}).values()
                if entry.get("status") == "tombstoned"
            ]
            controls = graph_pipeline.manifests.tombstone_controls(collection_tombstone_manifest)
            pending_digest = collection_tombstone_manifest.get("pending_tombstone_set_digest")
            if pending_digest is not None:
                controls = qdrant.write_tombstone_control_points(
                    tombstoned_entries,
                    collection_tombstone_manifest["tombstone_epoch"],
                    collection_tombstone_manifest["collection_operation_id"],
                    collection_tombstone_manifest["collection_fence_token"],
                    len(vectors[0]),
                )
                qdrant.verify_tombstone_control_points(controls, expected_digest=pending_digest)
                graph_pipeline.manifests.commit_tombstone_proof(controls)
            else:
                qdrant.verify_tombstone_control_points(
                    controls,
                    expected_digest=collection_tombstone_manifest["tombstone_set_digest"],
                )
            graph_claim = graph_pipeline.reserve(chunks, document_id, mode=ingest_mode)
            config["graph_claim"] = graph_claim
            qdrant.set_graph_claim(graph_pipeline.manifests, graph_claim)
        _print_stage(4, 4, "upload chunks", verbose, [
            f"Chunk count: {len(chunks)}",
            f"Vector size: {len(vectors[0])}",
        ])
        uploaded_point_ids = qdrant.upsert_chunks(chunks, vectors) or []
        if graph_pipeline and graph_claim:
            control_id = qdrant.write_document_control_point(graph_claim, len(vectors[0]))
            qdrant.verify_document_control_point(control_id)
        if ingest_mode == "replace-document":
            if graph_claim:
                qdrant.finalize_replace_document(document_id, uploaded_point_ids, graph_claim)
            else:
                qdrant.finalize_replace_document(document_id, uploaded_point_ids)
        elif ingest_mode == "replace-collection":
            if graph_claim:
                qdrant.set_collection_claim(
                    graph_pipeline.manifests,
                    collection_tombstone_manifest["collection_operation_id"],
                    collection_tombstone_manifest["collection_fence_token"],
                )
                qdrant.finalize_replace_collection(
                    uploaded_point_ids,
                    keep_control_ids={control["point_id"] for control in controls},
                )
                graph_pipeline.manifests.release_collection_fence(
                    collection_tombstone_manifest["collection_operation_id"],
                    collection_tombstone_manifest["collection_fence_token"],
                )
            else:
                qdrant.finalize_replace_collection(uploaded_point_ids)
    except Exception as exc:
        if graph_pipeline and graph_claim:
            try:
                graph_pipeline.manifests.fail(graph_claim, f"Qdrant ingest failed: {exc}")
            except Exception as fail_exc:
                raise RuntimeError("Qdrant failure status CAS failed; graph claim remains fail-closed") from fail_exc
        if isinstance(exc, ValueError):
            raise SystemExit(f"Error: {exc}") from exc
        raise

    graph_result = None
    if config.get("enable_graph_artifact", False):
        print("  Building persistent document graph (optional stage)...")
        graph_result = _build_ingest_graph_artifact(
            config, collection, document_id, chunks, vectors, ingest_mode
        )

    print(f"\n  Total chunks uploaded : {len(chunks)}")
    print(f"  Collection            : {collection}")
    if graph_result:
        print(f"  Graph artifact status : {graph_result.get('status', 'unavailable')}")
    print("  Ingest complete.")


def run_full_pipeline(config: dict) -> None:
    """Execute a Full-Pipeline Run with bounded adaptive retries."""
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
    max_retries = int(config.get("max_feedback_retries", 2))

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

    embedder = TextEmbedder()
    qdrant = QdrantHandler(collection_name=collection)
    if config.get("enable_graph_artifact", False):
        _configure_query_denial(qdrant, collection, config.get("graph_object_store"))
    extractor = EntityExtractor()
    graph_builder = GraphBuilder()
    detector = CommunityDetector()
    analyzer = GraphAnalyzer()
    pruner = SummaryPruner(top_k_per_community=3, top_k_global=10)
    prompt_builder = PromptBuilder(max_chars_per_chunk=1200)
    session = create_session()
    if verbose:
        resolved_chain = session.resolve_chain() if hasattr(session, "resolve_chain") else []
        if resolved_chain:
            print(f"  Resolved providers: {', '.join(resolved_chain)}")
    summarizer = LLMSummarizer(session=session)
    try:
        reducer = HierarchicalReducer(session=session, embedder=embedder)
    except TypeError:
        reducer = HierarchicalReducer(session=session)
    try:
        evaluator = SummaryEvaluator(judge_session=session)
    except TypeError:
        evaluator = SummaryEvaluator()
    checker = QualityChecker()
    controller = FeedbackLoopController(max_retries=max_retries)

    next_stage = "retrieval"
    attempt = 0
    retrieved_chunks = []
    ranked = None
    communities = []
    modularity = 0.0
    pruned_result = {"communities": []}
    community_prompts = []
    community_summaries = []

    while True:
        current_dir = artifact_dir if attempt == 0 else _artifact_path(artifact_dir, f"attempt-{attempt}")

        if next_stage == "retrieval":
            _print_stage(1, 8, "retrieve chunks", verbose, [
                f"Collection target: {collection}",
                f"Artifact directory: {current_dir}",
                f"Retrieval limit: {retrieval_limit}",
                f"Attempt: {attempt}",
            ])
            query_vector = embedder.embed_text(query)
            retrieved_chunks = qdrant.search_as_chunks(query_vector, limit=retrieval_limit)
            expand_parent_context = getattr(qdrant, "expand_parent_context", None)
            if callable(expand_parent_context):
                expanded_chunks = expand_parent_context(retrieved_chunks, max_depth=2)
                if isinstance(expanded_chunks, list):
                    retrieved_chunks = expanded_chunks
            elif verbose:
                print("  Parent context expansion unavailable; using retrieved payloads as-is.")
            print(f"\n  Retrieved chunks: {len(retrieved_chunks)}")
            retrieved_chunks = _maybe_render_images(retrieved_chunks, pdf_path)

            persistent_view = None
            persistent_graph_read_failed = False
            if config.get("enable_graph_artifact", False):
                try:
                    persistent_view = _persistent_graph_view(
                        collection, retrieved_chunks, config.get("graph_object_store")
                    )
                except Exception as exc:
                    _write_json_artifact(_artifact_path(current_dir, "persistent_graph_read.json"), {
                        "status": "unavailable",
                        "reason": f"{type(exc).__name__}: {exc}",
                    })
                    persistent_graph_read_failed = True
                    for chunk in retrieved_chunks:
                        chunk["graph_denied"] = True
            retrieved_chunks = [chunk for chunk in retrieved_chunks if not chunk.get("graph_denied")]
            if persistent_graph_read_failed:
                raise RuntimeError("persistent graph preflight failed; compatibility fallback denied")

            if persistent_view is None:
                _print_stage(2, 8, "extract entities and relations", verbose, f"Chunk count: {len(retrieved_chunks)}")
                entity_map, all_entities = extractor.extract_entities(retrieved_chunks)
                all_relations = []
                for chunk in retrieved_chunks:
                    rels = extractor.extract_relations_llm(
                        chunk["text"],
                        entity_map.get(chunk.get("chunk_uid", chunk["chunk_id"]), []),
                    )
                    all_relations.extend(rels)

                _print_stage(3, 8, "build graph", verbose, [
                    f"Entities: {len(all_entities)}",
                    f"Relations: {len(all_relations)}",
                ])
                chunk_embeddings = [embedder.embed_text(c["text"]) for c in retrieved_chunks]
                G = graph_builder.build_graph(retrieved_chunks, chunk_embeddings, all_entities, all_relations)

                _print_stage(4, 8, "detect communities", verbose)
                G, communities, community_map, modularity = detector.detect(G)
            else:
                _print_stage(2, 8, "load persistent graph artifact", verbose)
                G, communities, community_map, modularity = persistent_view
                _print_stage(3, 8, "reuse persisted graph", verbose, f"Communities: {len(communities)}")
                _print_stage(4, 8, "use persisted communities", verbose)

            _print_stage(5, 8, "rank graph and prune context", verbose, [
                f"Communities: {len(communities)}",
                f"Modularity: {modularity:.4f}",
            ])
            ranked = analyzer.analyze(G)
            analyzer.save_ranked_csv(ranked, _artifact_path(current_dir, "graph_ranked_nodes.csv"))
            analyzer.save_ranked_json(ranked, _artifact_path(current_dir, "graph_ranked_nodes.json"))
            analyzer.save_summary_json(ranked, communities, modularity, _artifact_path(current_dir, "graph_summary.json"))

            print(f"\n  Communities : {len(communities)}")
            print(f"  Modularity  : {modularity:.4f}")

            try:
                pruned_result = pruner.select_top_chunks(ranked, retrieved_chunks, graph=G)
            except TypeError:
                pruned_result = pruner.select_top_chunks(ranked, retrieved_chunks)
            pruner.save_pruned_json(pruned_result, _artifact_path(current_dir, "pruned_summary_context.json"))
            pruner.save_pruned_csv(pruned_result, _artifact_path(current_dir, "pruned_summary_context.csv"))
            next_stage = "prompt"

        if next_stage == "prompt":
            _print_stage(6, 8, "summarize communities", verbose)
            community_prompts = prompt_builder.build_all_community_prompts(pruned_result, query=query, style="concise")
            community_summaries = summarizer.summarize_communities(community_prompts)
            summarizer.save_map_summaries_json(community_summaries, _artifact_path(current_dir, "community_map_summaries.json"))
            summarizer.save_map_summaries_txt(community_summaries, _artifact_path(current_dir, "community_map_summaries.txt"))
            next_stage = "reduce"

        if next_stage == "reduce":
            _print_stage(7, 8, "reduce final summary", verbose, f"Community summaries: {len(community_summaries)}")
            final_result = reducer.reduce_summaries(community_summaries, query=query, style="concise")
            reducer.save_final_summary_json(final_result, _artifact_path(current_dir, "final_summary.json"))
            reducer.save_final_summary_txt(final_result, _artifact_path(current_dir, "final_summary.txt"))

            print("\n  Final Summary:")
            print(f"  {final_result['final_summary'][:200]}...")

            _print_stage(8, 8, "evaluate quality and decide", verbose)
            try:
                eval_result = evaluator.evaluate_without_reference(
                    generated_summary=final_result["final_summary"],
                    source_chunks=retrieved_chunks,
                    query=query,
                )
            except TypeError:
                eval_result = evaluator.evaluate_without_reference(
                    generated_summary=final_result["final_summary"],
                    source_chunks=retrieved_chunks,
                )
            evaluator.save_evaluation_json(eval_result, _artifact_path(current_dir, "evaluation_result.json"))

            quality_result = checker.check(eval_result)
            action_result = checker.suggest_action(quality_result)
            checker.save_quality_report(quality_result, action_result, _artifact_path(current_dir, "quality_gate_report.json"))

            print(f"\n  Quality Status  : {quality_result['status']}")
            print(f"  Suggested Action: {action_result['action']}")

            decision = controller.decide(
                quality_result=quality_result,
                action_result=action_result,
                retry_state=retry_state,
            )
            controller.save_decision(decision, _artifact_path(current_dir, "feedback_loop_decision.json"))
            print(f"\n  Decision: {decision.get('final_decision')}")

            if decision.get("stop", True):
                break

            retry_state = decision.get("updated_retry_state", retry_state)
            next_stage = decision.get("next_stage") or "reduce"
            attempt += 1
            if next_stage == "retrieval":
                retrieval_limit += 2


def _maybe_render_images(retrieved_chunks: list, pdf_path: str) -> list:
    """Optionally render page images if on-demand mode is enabled and PDF is available."""
    from config import settings
    from launcher.contract import suggest_document_id_from_pdf

    if not settings.ENABLE_ON_DEMAND_PAGE_RENDER:
        return retrieved_chunks
    document_ids = {
        chunk.get("document_id")
        for chunk in retrieved_chunks
        if chunk.get("document_id")
    }
    if not pdf_path:
        sources = {chunk.get("source") for chunk in retrieved_chunks if chunk.get("source")}
        if len(sources) > 1 or len(document_ids) > 1:
            print("⚠️ Mixed-document retrieval: page images skipped because no local PDF was provided.")
        return retrieved_chunks

    from preprocessing.docling_loader import DoclingLoader

    loader = DoclingLoader()
    pdf_source = Path(pdf_path).name
    local_document_id = suggest_document_id_from_pdf(pdf_path)
    if len(document_ids) > 1:
        matching_chunks = [
            chunk for chunk in retrieved_chunks
            if chunk.get("document_id") == local_document_id
        ]
        if not matching_chunks:
            print("⚠️ Mixed-document retrieval: page images skipped because document IDs are ambiguous.")
            return retrieved_chunks
        print(f"⚠️ Mixed-document retrieval: page images limited to document '{local_document_id}'.")
    else:
        matching_chunks = [
            chunk for chunk in retrieved_chunks
            if not chunk.get("source") or chunk.get("source") == pdf_source
        ]
    if document_ids and local_document_id not in document_ids:
        print("⚠️ Page images skipped: retrieved document ID does not match the local PDF.")
        return retrieved_chunks
    other_sources = {
        chunk.get("source")
        for chunk in retrieved_chunks
        if chunk.get("source") and chunk.get("source") != pdf_source
    }
    if other_sources:
        print(f"⚠️ Mixed-document retrieval: page images limited to local source '{pdf_source}'.")
    if not matching_chunks:
        return retrieved_chunks
    target_pages = sorted({
        c.get("page_no")
        for c in matching_chunks
        if isinstance(c.get("page_no"), int)
    })
    if not target_pages:
        return retrieved_chunks

    uploaded = loader.render_and_upload_pages_on_demand(pdf_path=pdf_path, target_pages=target_pages)
    page_image_map = loader.build_page_image_map(uploaded)
    for chunk in matching_chunks:
        page_no = chunk.get("page_no")
        if page_no in page_image_map:
            chunk["image_url"] = page_image_map[page_no]

    print(f"  On-demand images uploaded: {len(uploaded)}")
    return retrieved_chunks
