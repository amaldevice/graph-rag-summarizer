# ============================================================
# MODE RUNNERS
# Execute a single Launcher Mode with resolved config.
# ============================================================

import json
import os
import uuid
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


def _empty_relation_recovery_diagnostics() -> dict:
    """Return the stable empty shape for optional ingest recovery diagnostics."""
    return {
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


def _compatibility_relation_recovery_diagnostics() -> dict:
    """Record that query-time fallback intentionally does not run recovery."""
    return {
        "status": "not_run",
        "reason": "compatibility_fallback",
        **_empty_relation_recovery_diagnostics(),
    }


def _empty_context_allocation_diagnostics() -> dict:
    """Keep the optional allocation artifact inspectable for legacy pruners."""
    return {
        "strategy": "adaptive_character_budget",
        "character_budget": 0,
        "consumed_characters": 0,
        "remaining_characters": 0,
        "path_signal_status": "unavailable",
        "communities": [],
        "selected_chunks": [],
        "rejected_chunks": [],
    }


def _context_allocation_artifact(
    pruned_result: dict,
    *,
    graph_source: str,
    fallback_status: str,
    fallback_reason: str,
    query_protected_chunk_uids: set,
    attempt: int,
) -> dict:
    """Add runner-owned provenance without changing allocator decisions."""
    allocation = pruned_result.get("context_allocation") if isinstance(pruned_result, dict) else None
    allocator_status = "available"
    if not isinstance(allocation, dict):
        allocation = _empty_context_allocation_diagnostics()
        allocator_status = "unavailable"
    else:
        allocation = dict(allocation)
    allocation["runner_context"] = {
        "attempt": attempt,
        "allocator_status": allocator_status,
        "graph_source": graph_source,
        "fallback_status": fallback_status,
        "fallback_reason": fallback_reason,
        "query_protected_chunk_uids": sorted(
            str(chunk_uid) for chunk_uid in query_protected_chunk_uids
        ),
    }
    return allocation


def _prompt_delivery_diagnostics(community_prompts: list[dict]) -> list[dict]:
    """Persist the final prompt budget and provider safety gate per community."""
    return [
        {
            "community_id": prompt.get("community_id", -1),
            "budget": prompt["budget"],
            "provider_safety": prompt["provider_safety"],
        }
        for prompt in community_prompts
        if isinstance(prompt, dict)
        and isinstance(prompt.get("budget"), dict)
        and isinstance(prompt.get("provider_safety"), dict)
    ]


def _evaluation_source_chunks(pruned_result: dict, retrieved_chunks: list[dict]) -> list[dict]:
    """Use the explicit selected evidence; support legacy pruners that omit it."""
    selected = pruned_result.get("global_top_chunks") if isinstance(pruned_result, dict) else None
    return selected if isinstance(selected, list) else retrieved_chunks


def _chunk_query_key(chunk: dict):
    """Prefer stable document-scoped identities when protecting retrieval hits."""
    chunk_uid = chunk.get("chunk_uid")
    if chunk_uid is not None:
        return ("uid", str(chunk_uid))
    document_id = chunk.get("document_id")
    chunk_id = chunk.get("chunk_id")
    if document_id is not None:
        return ("document", str(document_id), str(chunk_id))
    return ("local", str(chunk_id))


def _mark_retrieval_hits_query_protected(chunks: list[dict], retrieval_keys: set) -> set:
    """Protect original retrieval hits only; expanded hierarchy context stays eligible."""
    protected_chunk_uids = set()
    for chunk in chunks:
        chunk["query_protected"] = _chunk_query_key(chunk) in retrieval_keys
        if chunk["query_protected"]:
            chunk_uid = chunk.get("chunk_uid", chunk.get("chunk_id"))
            if chunk_uid is not None:
                protected_chunk_uids.add(chunk_uid)
    return protected_chunk_uids


def _build_ingest_graph_artifact(config, collection, document_id, chunks, vectors, ingest_mode):
    """Build the baseline graph after vector upload; vectors survive graph failure."""
    status_path = _artifact_path(config.get("artifact_dir") or "output", "graph_artifact_status.json")
    lifecycle_error = None
    from graph.persistent import GraphLifecycleError, PersistentGraphPipeline
    try:
        pipeline = config.get("graph_pipeline") or PersistentGraphPipeline(
            collection, object_store=config.get("graph_object_store")
        )
        result = pipeline.build_and_publish(
            chunks,
            vectors,
            document_id,
            mode=ingest_mode,
            claim=config.get("graph_claim"),
            qdrant=config.get("qdrant"),
            relation_provider=config.get("graph_relation_provider"),
        )
    except GraphLifecycleError as exc:
        lifecycle_error = exc
        result = {"status": "unavailable", "failure_reason": f"{type(exc).__name__}: {exc}"}
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
    if lifecycle_error is not None:
        raise lifecycle_error
    return result


def _validated_persistent_graph_artifact(manifests, artifacts, document_id, chunks):
    """Return one validated query graph and its immutable artifact body."""
    from graph.persistent import (
        GraphArtifactCorruptionError,
        deserialize_graph,
        graph_from_artifact,
    )
    import networkx as nx

    snapshot = manifests.read_snapshot()
    entry = snapshot.manifest.get("documents", {}).get(document_id)
    if not entry or entry.get("status") != "available" or not entry.get("active_artifact_key"):
        return None
    data = artifacts.read(
        entry["active_artifact_key"],
        entry.get("artifact_digest"),
        entry.get("backend"),
        entry.get("document_generation"),
        entry.get("source_fingerprint"),
    )
    try:
        artifact = deserialize_graph(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GraphArtifactCorruptionError("graph artifact body is not valid JSON") from exc
    if (
        not isinstance(artifact, dict)
        or artifact.get("document_id") != document_id
        or artifact.get("document_generation") != entry.get("document_generation")
        or artifact.get("source_fingerprint") != entry.get("source_fingerprint")
    ):
        raise GraphArtifactCorruptionError("graph artifact body metadata mismatch")
    if not manifests.revalidate(snapshot):
        raise RuntimeError("manifest changed while reading graph artifact")
    try:
        graph = graph_from_artifact(artifact, chunks)
        if chunks:
            by_uid = {chunk.get("chunk_uid"): index for index, chunk in enumerate(chunks)}
            mapping = {
                node: f"chunk_{by_uid[attrs.get('chunk_uid')]}"
                for node, attrs in graph.nodes(data=True)
                if attrs.get("type") == "chunk" and attrs.get("chunk_uid") in by_uid
            }
            graph = nx.relabel_nodes(graph, mapping, copy=True)
    except (KeyError, TypeError, ValueError, nx.NetworkXError) as exc:
        raise GraphArtifactCorruptionError("graph artifact graph structure is invalid") from exc
    if not isinstance(artifact.get("raw_evidence", []), list):
        raise GraphArtifactCorruptionError("graph artifact relation evidence is invalid")
    if not isinstance(artifact.get("active_evidence", []), list):
        raise GraphArtifactCorruptionError("graph artifact active evidence is invalid")
    if not isinstance(artifact.get("diagnostics", {}), dict):
        raise GraphArtifactCorruptionError("graph artifact diagnostics are invalid")
    return graph, artifact


def _with_current_query_protection(entity_support, canonicalization, retrieved_chunks):
    """Overlay query-time protection without changing immutable artifact diagnostics."""
    current_chunk_uids = {
        str(chunk.get("chunk_uid", chunk.get("chunk_id")))
        for chunk in retrieved_chunks
        if chunk.get("query_protected")
        and chunk.get("chunk_uid", chunk.get("chunk_id")) is not None
    }
    protected_ids = set()
    if isinstance(canonicalization, dict):
        canonical_entities = canonicalization.get("canonical_entities", [])
        if isinstance(canonical_entities, list):
            for entity in canonical_entities:
                if not isinstance(entity, dict) or not entity.get("canonical_id"):
                    continue
                chunk_uids = entity.get("chunk_uids", [])
                if isinstance(chunk_uids, str):
                    chunk_uids = [chunk_uids]
                if isinstance(chunk_uids, list) and current_chunk_uids.intersection(
                    str(chunk_uid) for chunk_uid in chunk_uids if chunk_uid is not None
                ):
                    protected_ids.add(str(entity["canonical_id"]))

    if not isinstance(entity_support, dict):
        return entity_support
    report = dict(entity_support)
    elements = entity_support.get("elements", [])
    if isinstance(elements, list):
        report["elements"] = [
            {
                **element,
                "query_protected": str(element.get("canonical_id")) in protected_ids,
            }
            if isinstance(element, dict) else element
            for element in elements
        ]
    report["query_protected"] = sorted(protected_ids)
    return report


def _persistent_graph_view(collection, chunks, object_store=None):
    """Load namespaced persisted document graphs; return None for compatibility fallback."""
    from graph.persistent import GraphArtifactCorruptionError, default_graph_services
    import networkx as nx

    document_ids = sorted({chunk.get("document_id") for chunk in chunks if chunk.get("document_id")})
    if not document_ids:
        return None
    manifests, artifacts = default_graph_services(collection, object_store)
    merged = nx.Graph()
    diagnostics_by_document = {}
    found = False
    fallback_required = False
    for document_id in document_ids:
        document_chunks = [chunk for chunk in chunks if chunk.get("document_id") == document_id]
        if not manifests.preflight(document_id)["allowed"]:
            for chunk in document_chunks:
                chunk["graph_denied"] = True
            continue
        try:
            loaded = _validated_persistent_graph_artifact(
                manifests, artifacts, document_id, document_chunks
            )
        except (FileNotFoundError, GraphArtifactCorruptionError):
            # Rebuild the compatibility view for the whole query when one
            # document artifact is unavailable; tombstone and manifest
            # authorization failures remain fail-closed.
            fallback_required = True
            continue
        if loaded is None:
            fallback_required = True
            continue
        graph, artifact = loaded
        found = True
        diagnostics_by_document[document_id] = {
            "raw_evidence": artifact.get("raw_evidence", []),
            "active_evidence": artifact.get("active_evidence", []),
            "diagnostics": artifact.get("diagnostics", {}),
        }
        mapping = {}
        for node, attrs in graph.nodes(data=True):
            if attrs.get("type") == "chunk":
                local_index = next((i for i, chunk in enumerate(chunks) if chunk.get("chunk_uid") == attrs.get("chunk_uid")), None)
                if local_index is not None:
                    mapping[node] = f"chunk_{local_index}"
            else:
                mapping[node] = f"{document_id}::{node}"
        merged = nx.compose(merged, nx.relabel_nodes(graph, mapping, copy=True))
    if not found or fallback_required:
        return None
    communities = {}
    community_map = {}
    for node, attrs in merged.nodes(data=True):
        community = attrs.get("community", -1)
        community_map[node] = community
        communities.setdefault(community, []).append(node)
    return (
        merged,
        communities,
        community_map,
        float(merged.graph.get("modularity", 0.0)),
        {"documents": diagnostics_by_document},
    )


def _compatibility_query_graph_view(
    chunks,
    *,
    embedder,
    extractor,
    graph_builder,
    detector,
    query_protected_chunk_uids,
):
    """Build the legacy query graph and return the artifacts it would produce."""
    from graph.relation_evidence import (
        canonicalize_entities,
        classify_entity_support,
        classify_weak_relation_evidence,
        is_active_relation,
        normalize_relation_evidence,
    )

    entity_map, extracted_entities = extractor.extract_entities(chunks)
    all_entities, canonicalization = canonicalize_entities(extracted_entities)
    mentions_by_chunk_uid = {}
    for mention in extracted_entities:
        mention_chunk_uid = mention.get("chunk_uid", mention.get("chunk_id"))
        mentions_by_chunk_uid.setdefault(mention_chunk_uid, []).append(mention)
    all_relations = []
    for chunk in chunks:
        chunk_uid = chunk.get("chunk_uid", chunk["chunk_id"])
        relations = extractor.extract_relations_llm(
            chunk["text"], entity_map.get(chunk_uid, [])
        )
        relations = [
            {
                **relation,
                "evidence_type": classify_weak_relation_evidence(
                    relation, mentions_by_chunk_uid.get(chunk_uid, [])
                ),
            }
            if str(relation.get("source", "")).casefold() in {"rule-based", "fallback"}
            else relation
            for relation in relations
        ]
        all_relations.extend(
            normalize_relation_evidence(relations, support_chunk_uid=chunk_uid)
        )
    all_relations = normalize_relation_evidence(all_relations)
    active_evidence = [relation for relation in all_relations if is_active_relation(relation)]
    status_counts = {
        status: sum(
            1 for relation in all_relations
            if relation.get("status", "unknown") == status
        )
        for status in sorted({relation.get("status", "unknown") for relation in all_relations})
    }
    chunk_embeddings = [embedder.embed_text(chunk["text"]) for chunk in chunks]
    graph = graph_builder.build_graph(
        chunks, chunk_embeddings, all_entities, all_relations
    )
    try:
        graph, communities, community_map, modularity = detector.detect(
            graph, chunk_embeddings
        )
    except TypeError:
        graph, communities, community_map, modularity = detector.detect(graph)
    entity_support = classify_entity_support(
        all_entities,
        all_relations,
        graph=graph,
        query_protected_chunk_uids=query_protected_chunk_uids,
    )
    graph_metadata = getattr(graph, "graph", {})
    if not isinstance(graph_metadata, dict):
        graph_metadata = {}
    return {
        "graph": graph,
        "communities": communities,
        "community_map": community_map,
        "modularity": modularity,
        "all_relations": all_relations,
        "active_evidence": active_evidence,
        "status_counts": status_counts,
        "canonicalization": canonicalization,
        "entity_support": entity_support,
        "community_selection": graph_metadata.get("community_selection", {}),
        "embedding_comparison": graph_metadata.get(
            "embedding_cluster_comparison", {}
        ),
        "relation_recovery": _compatibility_relation_recovery_diagnostics(),
    }


def _vector_only_query_graph_view(chunks, reason):
    """Keep vector-retrieved chunks summarizable when query graph work fails."""
    import networkx as nx

    graph = nx.Graph()
    nodes = []
    for index, chunk in enumerate(chunks):
        node = f"chunk_{index}"
        nodes.append(node)
        graph.add_node(
            node,
            type="chunk",
            text=chunk.get("text", ""),
            community=0,
            query_protected=bool(chunk.get("query_protected")),
        )
    graph.graph["vector_only"] = True
    graph.graph["fallback_reason"] = reason
    return {
        "graph": graph,
        "communities": {0: nodes} if nodes else {},
        "community_map": {node: 0 for node in nodes},
        "modularity": 0.0,
        "all_relations": [],
        "active_evidence": [],
        "status_counts": {},
        "canonicalization": {
            "status": "not_run",
            "reason": "vector_only_fallback",
            "canonical_entities": [],
            "unresolved_aliases": [],
        },
        "entity_support": {
            "status": "not_run",
            "reason": "vector_only_fallback",
            "elements": [],
            "strongly_supported": [],
            "weakly_supported": [],
            "mention_only": [],
            "isolated_noise_candidates": [],
            "query_protected": [],
            "relation_orphans": [],
        },
        "community_selection": {
            "status": "not_run",
            "reason": "vector_only_fallback",
        },
        "embedding_comparison": {
            "status": "not_run",
            "reason": "vector_only_fallback",
        },
        "relation_recovery": {
            "status": "not_run",
            "reason": "vector_only_fallback",
            **_empty_relation_recovery_diagnostics(),
        },
    }


def _compatibility_or_vector_view(
    chunks,
    *,
    embedder,
    extractor,
    graph_builder,
    detector,
    query_protected_chunk_uids,
):
    """Use compatibility graph evidence when available, otherwise vector retrieval."""
    try:
        return _compatibility_query_graph_view(
            chunks,
            embedder=embedder,
            extractor=extractor,
            graph_builder=graph_builder,
            detector=detector,
            query_protected_chunk_uids=query_protected_chunk_uids,
        ), None
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        return _vector_only_query_graph_view(chunks, reason), reason


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
    expected_digest = snapshot.manifest.get("tombstone_set_digest")
    if not isinstance(expected_digest, str) or not expected_digest:
        raise RuntimeError("manifest tombstone digest is missing; query denied")
    qdrant.verify_tombstone_control_points(
        manifests_tombstones,
        expected_digest=expected_digest,
    )
    if not manifests.revalidate(snapshot):
        raise RuntimeError("manifest changed during tombstone preflight")
    denied = [
        document_id
        for document_id, entry in snapshot.manifest.get("documents", {}).items()
        if entry.get("status") == "tombstoned"
    ]
    qdrant.set_denied_document_ids(denied)
    qdrant.set_query_authorization(manifests, snapshot)
    manifest_entries = snapshot.manifest.get("documents", {})
    if not manifest_entries:
        # Without a manifest there is no authoritative current generation.
        qdrant.set_active_vector_generations({})
    else:
        active_vector_generations = {}
        for document_id, entry in manifest_entries.items():
            if entry.get("status") == "tombstoned":
                continue
            if entry.get("status") == "pending":
                generation = (entry.get("previous_pointer") or {}).get("document_generation")
            elif entry.get("status") in {"partial", "unavailable", "stale"} and not entry.get("vector_ready"):
                generation = None
            else:
                generation = entry.get("document_generation")
            if generation is not None:
                active_vector_generations[document_id] = generation
        qdrant.set_active_vector_generations(active_vector_generations)
    qdrant.set_active_graph_selectors({
        document_id: {
            "document_generation": entry["document_generation"],
            "document_attempt_id": entry["document_attempt_id"],
        }
        for document_id, entry in snapshot.manifest.get("documents", {}).items()
        if entry.get("status") == "available"
        and entry.get("document_generation") is not None
        and entry.get("document_attempt_id") is not None
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
    config["qdrant"] = qdrant
    # Query authorization is a safety boundary, not a graph-rendering feature.
    # Disabling graph artifacts may skip graph reads, but must not re-expose a
    # document that a collection replacement has tombstoned.
    _configure_query_denial(qdrant, collection, config.get("graph_object_store"))
    embedder = TextEmbedder()
    query_vector = embedder.embed_text(query)

    _print_stage(2, 3, "retrieve chunks", verbose, f"Retrieval limit: {retrieval_limit}")
    chunks = qdrant.search_as_chunks(query_vector, limit=retrieval_limit)
    qdrant.revalidate_query_authorization()

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
            from graph.persistent import PersistentGraphPipeline, source_fingerprint

            graph_pipeline = PersistentGraphPipeline(
                collection, object_store=config.get("graph_object_store")
            )
            config["graph_pipeline"] = graph_pipeline
            if ingest_mode != "replace-collection":
                graph_claim = graph_pipeline.reserve(chunks, document_id, mode=ingest_mode)
                config["graph_claim"] = graph_claim
        except Exception as exc:
            raise RuntimeError(
                f"persistent graph reservation failed before vector mutation: {type(exc).__name__}: {exc}"
            ) from exc

    _print_stage(3, 4, "prepare collection", verbose, [
        f"Collection target: {collection}",
        f"Operation: {ingest_mode}",
        f"Document ID: {document_id}",
    ])
    qdrant = QdrantHandler(collection_name=collection)
    config["qdrant"] = qdrant
    if graph_pipeline and ingest_mode == "replace-collection":
        persisted_operation_id = graph_pipeline.manifests.read_snapshot().manifest.get("collection_operation_id")
        collection_operation_id = config.get("collection_operation_id") or persisted_operation_id or (
            f"replace-collection:{collection}:{document_id}:{uuid.uuid4()}"
        )
        collection_tombstone_manifest = graph_pipeline.manifests.tombstone_documents(
            {document_id: source_fingerprint(chunks, document_id)}, collection_operation_id
        )
        qdrant.set_collection_claim(
            graph_pipeline.manifests,
            collection_operation_id,
            collection_tombstone_manifest["collection_fence_token"],
            collection_tombstone_manifest["collection_attempt_id"],
        )
        existing_entry = graph_pipeline.manifests.get(document_id)
        if (
            existing_entry
            and existing_entry.get("status") == "available"
            and existing_entry.get("source_fingerprint") == source_fingerprint(chunks, document_id)
            and isinstance(existing_entry.get("document_attempt_id"), str)
            and existing_entry["document_attempt_id"]
            and existing_entry.get("collection_fence_token") == collection_tombstone_manifest.get("collection_fence_token")
            and existing_entry.get("collection_attempt_id") == collection_tombstone_manifest.get("collection_attempt_id")
            and collection_tombstone_manifest.get("pending_tombstone_set_digest") is None
        ):
            artifact_key = existing_entry.get("active_artifact_key")
            artifact_digest = existing_entry.get("artifact_digest")
            artifact_backend = existing_entry.get("backend")
            document_generation = existing_entry.get("document_generation")
            if not (
                isinstance(artifact_key, str)
                and artifact_key
                and isinstance(artifact_digest, str)
                and artifact_digest
                and isinstance(artifact_backend, dict)
                and isinstance(artifact_backend.get("kind"), str)
                and artifact_backend["kind"]
                and isinstance(artifact_backend.get("namespace"), str)
                and artifact_backend["namespace"]
                and isinstance(document_generation, int)
                and not isinstance(document_generation, bool)
                and document_generation > 0
            ):
                raise RuntimeError("completed replace-collection resume has an incomplete artifact tuple")
            try:
                graph_pipeline.artifacts.read(
                    artifact_key,
                    artifact_digest,
                    artifact_backend,
                    document_generation,
                    existing_entry["source_fingerprint"],
                )
            except Exception as exc:
                raise RuntimeError(
                    "completed replace-collection resume artifact validation failed"
                ) from exc
            qdrant.verify_collection_tombstone_proof(graph_pipeline.manifests)
            current_collection_manifest = graph_pipeline.manifests.read_snapshot().manifest
            if (
                current_collection_manifest.get("collection_operation_id")
                != collection_tombstone_manifest.get("collection_operation_id")
                or current_collection_manifest.get("collection_fence_token")
                != collection_tombstone_manifest.get("collection_fence_token")
                or current_collection_manifest.get("collection_attempt_id")
                != collection_tombstone_manifest.get("collection_attempt_id")
                or current_collection_manifest.get("pending_tombstone_set_digest") is not None
            ):
                raise RuntimeError("completed replace-collection resume lost its collection fence")
            graph_pipeline.manifests.release_collection_fence(
                current_collection_manifest["collection_operation_id"],
                current_collection_manifest["collection_fence_token"],
            )
            print("  Resumed completed replace-collection graph publication.")
            print(f"\n  Total chunks uploaded : {len(chunks)}")
            print(f"  Collection            : {collection}")
            print("  Graph artifact status : available")
            print("  Ingest complete.")
            return

    if graph_pipeline and graph_claim:
        qdrant.set_graph_claim(graph_pipeline.manifests, graph_claim)

    try:
        prepare_kwargs = {
            "ingest_mode": ingest_mode,
            "document_id": document_id,
            "vector_size": len(vectors[0]),
        }
        if graph_claim is not None:
            prepare_kwargs["claim"] = graph_claim
        qdrant.prepare_ingest(**prepare_kwargs)
        if ingest_mode == "replace-collection":
            qdrant.capture_collection_baseline()
        if graph_pipeline and collection_tombstone_manifest:
            tombstoned_entries = [
                entry for entry in collection_tombstone_manifest.get("documents", {}).values()
                if entry.get("status") == "tombstoned"
            ]
            controls = graph_pipeline.manifests.tombstone_controls(collection_tombstone_manifest)
            pending_digest = collection_tombstone_manifest.get("pending_tombstone_set_digest")
            if pending_digest is not None:
                expected_digest = graph_pipeline.manifests.tombstone_proof_digest(collection_tombstone_manifest)
                controls = qdrant.write_tombstone_control_points(
                    tombstoned_entries,
                    collection_tombstone_manifest["tombstone_epoch"],
                    collection_tombstone_manifest["collection_operation_id"],
                    collection_tombstone_manifest["collection_fence_token"],
                    len(vectors[0]),
                    collection_tombstone_manifest["collection_attempt_id"],
                )
                qdrant.verify_tombstone_control_points(
                    controls,
                    expected_digest=expected_digest,
                    allow_stale_control_ids=set(collection_tombstone_manifest.get("pending_tombstone_cleanup_ids", [])),
                )
                collection_tombstone_manifest = graph_pipeline.manifests.commit_tombstone_proof(controls)
            else:
                qdrant.verify_tombstone_control_points(
                    controls,
                    expected_digest=graph_pipeline.manifests.tombstone_proof_digest(collection_tombstone_manifest),
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
            graph_pipeline.manifests.mark_vectors_ready(graph_claim)
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
                    collection_tombstone_manifest["collection_attempt_id"],
                )
                qdrant.finalize_replace_collection(
                    uploaded_point_ids,
                    keep_control_ids={control["point_id"] for control in controls} | {control_id},
                    remove_control_ids=set(collection_tombstone_manifest.get("pending_tombstone_cleanup_ids", [])),
                )
                current_collection_manifest = graph_pipeline.manifests.read_snapshot().manifest
                current_controls = graph_pipeline.manifests.tombstone_controls(current_collection_manifest)
                qdrant.verify_tombstone_control_points(
                    current_controls,
                    expected_digest=graph_pipeline.manifests.tombstone_proof_digest(current_collection_manifest),
                )
                collection_tombstone_manifest = current_collection_manifest
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
        if config.get("graph_relation_provider") is None:
            from summarizer.provider_router import create_session

            config["graph_relation_provider"] = create_session()
        print("  Building persistent document graph (optional stage)...")
        graph_result = _build_ingest_graph_artifact(
            config, collection, document_id, chunks, vectors, ingest_mode
        )
    if graph_pipeline and collection_tombstone_manifest and graph_claim:
        qdrant.verify_collection_tombstone_proof(graph_pipeline.manifests)
        current_collection_manifest = graph_pipeline.manifests.read_snapshot().manifest
        if current_collection_manifest.get("pending_tombstone_set_digest") is not None:
            if not graph_result or graph_result.get("status") != "available":
                raise RuntimeError(
                    "replacement graph was not published; tombstone cleanup remains pending and collection fence stays held"
                )
            graph_pipeline.manifests.finalize_tombstone_cleanup(
                collection_tombstone_manifest["collection_operation_id"],
                collection_tombstone_manifest["collection_fence_token"],
            )
        if graph_pipeline.manifests.read_snapshot().manifest.get("pending_tombstone_set_digest") is None:
            graph_pipeline.manifests.release_collection_fence(
                collection_tombstone_manifest["collection_operation_id"],
                collection_tombstone_manifest["collection_fence_token"],
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
    from graph.relation_evidence import (
        canonicalize_entities,
        classify_entity_support,
        classify_weak_relation_evidence,
        is_active_relation,
        normalize_relation_evidence,
    )
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
    forced_retry_stage = config.get("_test_force_feedback_retry_stage")
    if forced_retry_stage not in {None, "retrieval", "prompt", "reduce"}:
        raise ValueError("_test_force_feedback_retry_stage must be retrieval, prompt, or reduce")

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
    # Keep tombstone and generation authorization enabled even when callers
    # opt out of graph artifact reads.
    _configure_query_denial(qdrant, collection, config.get("graph_object_store"))
    session = create_session()
    # Relation extraction shares the configured provider router and its
    # sequential fallback chain with summarization and reduction.
    extractor = EntityExtractor(provider_router=session)
    graph_builder = GraphBuilder()
    detector = CommunityDetector()
    analyzer = GraphAnalyzer()
    allocation_options = {
        "context_char_budget": config.get("context_char_budget", 12000),
        "min_community_chars": config.get("min_community_chars", 600),
        "max_community_chars": config.get("max_community_chars", 4800),
        "relevance_floor": config.get("context_relevance_floor", 0.05),
        "min_marginal_gain": config.get("min_marginal_gain", 0.01),
    }
    try:
        pruner = SummaryPruner(
            top_k_per_community=3,
            top_k_global=10,
            **allocation_options,
        )
    except TypeError:
        # Keep third-party/legacy pruners working while allocation rolls out.
        pruner = SummaryPruner(top_k_per_community=3, top_k_global=10)
    try:
        prompt_builder = PromptBuilder(
            max_chars_per_chunk=1200,
            provider_context_token_limit=config.get("provider_context_token_limit", 4096),
            reserved_output_tokens=400,
        )
    except TypeError:
        # Keep third-party/legacy prompt builders working while the safety gate rolls out.
        prompt_builder = PromptBuilder(max_chars_per_chunk=1200)
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
    context_allocation = None
    context_graph_source = "not_run"
    context_fallback_status = "not_run"
    context_fallback_reason = ""
    query_protected_chunk_uids = set()
    community_prompts = []
    community_summaries = []

    while True:
        current_dir = artifact_dir if attempt == 0 else _artifact_path(artifact_dir, f"attempt-{attempt}")

        if next_stage != "retrieval" and context_allocation is not None:
            _write_json_artifact(
                _artifact_path(current_dir, "context_allocation.json"),
                _context_allocation_artifact(
                    pruned_result,
                    graph_source=context_graph_source,
                    fallback_status=context_fallback_status,
                    fallback_reason=context_fallback_reason,
                    query_protected_chunk_uids=query_protected_chunk_uids,
                    attempt=attempt,
                ),
            )

        if next_stage == "retrieval":
            _print_stage(1, 8, "retrieve chunks", verbose, [
                f"Collection target: {collection}",
                f"Artifact directory: {current_dir}",
                f"Retrieval limit: {retrieval_limit}",
                f"Attempt: {attempt}",
            ])
            query_vector = embedder.embed_text(query)
            retrieved_chunks = qdrant.search_as_chunks(query_vector, limit=retrieval_limit)
            query_protected_keys = {
                _chunk_query_key(chunk) for chunk in retrieved_chunks
            }
            qdrant.revalidate_query_authorization()
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
            persistent_graph_read_reason = ""
            if config.get("enable_graph_artifact", False):
                try:
                    persistent_view = _persistent_graph_view(
                        collection, retrieved_chunks, config.get("graph_object_store")
                    )
                except Exception as exc:
                    persistent_graph_read_reason = f"{type(exc).__name__}: {exc}"
                    _write_json_artifact(_artifact_path(current_dir, "persistent_graph_read.json"), {
                        "status": "unavailable",
                        "reason": persistent_graph_read_reason,
                    })
            qdrant.revalidate_query_authorization()
            retrieved_chunks = [chunk for chunk in retrieved_chunks if not chunk.get("graph_denied")]
            query_protected_chunk_uids = _mark_retrieval_hits_query_protected(
                retrieved_chunks, query_protected_keys
            )

            if persistent_view is None:
                context_graph_source = "compatibility_query_graph"
                context_fallback_status = (
                    "persistent_graph_unavailable"
                    if config.get("enable_graph_artifact", False)
                    else "persistent_graph_disabled"
                )
                context_fallback_reason = persistent_graph_read_reason
                _print_stage(2, 8, "extract entities and relations", verbose, f"Chunk count: {len(retrieved_chunks)}")
                compatibility_view, compatibility_failure = _compatibility_or_vector_view(
                    retrieved_chunks,
                    embedder=embedder,
                    extractor=extractor,
                    graph_builder=graph_builder,
                    detector=detector,
                    query_protected_chunk_uids=query_protected_chunk_uids,
                )
                if compatibility_failure:
                    context_graph_source = "vector_only"
                    context_fallback_status = "compatibility_graph_failed"
                    context_fallback_reason = compatibility_failure
                    _write_json_artifact(_artifact_path(current_dir, "graph_fallback.json"), {
                        "graph_source": context_graph_source,
                        "fallback_status": context_fallback_status,
                        "fallback_reason": context_fallback_reason,
                    })
                    _print_stage(3, 8, "use vector-only context", verbose)
                else:
                    _print_stage(3, 8, "build graph", verbose)
                    _print_stage(4, 8, "detect communities", verbose)
                G = compatibility_view["graph"]
                communities = compatibility_view["communities"]
                community_map = compatibility_view["community_map"]
                modularity = compatibility_view["modularity"]
                _write_json_artifact(_artifact_path(current_dir, "relation_evidence.json"), {
                    "raw_evidence": compatibility_view["all_relations"],
                    "active_evidence": compatibility_view["active_evidence"],
                    "counts": {
                        "raw_evidence_count": len(compatibility_view["all_relations"]),
                        "active_evidence_count": len(compatibility_view["active_evidence"]),
                        "relation_status_counts": compatibility_view["status_counts"],
                    },
                })
                _write_json_artifact(
                    _artifact_path(current_dir, "entity_canonicalization.json"),
                    compatibility_view["canonicalization"],
                )
                _write_json_artifact(
                    _artifact_path(current_dir, "orphan_node_report.json"),
                    compatibility_view["entity_support"],
                )
                _write_json_artifact(
                    _artifact_path(current_dir, "relation_recovery.json"),
                    compatibility_view["relation_recovery"],
                )
                community_selection = compatibility_view["community_selection"]
                embedding_comparison = compatibility_view["embedding_comparison"]
            else:
                context_graph_source = "persistent_graph"
                context_fallback_status = "not_used"
                context_fallback_reason = ""
                _print_stage(2, 8, "load persistent graph artifact", verbose)
                G, communities, community_map, modularity, persisted_diagnostics = persistent_view
                _print_stage(3, 8, "reuse persisted graph", verbose, f"Communities: {len(communities)}")
                _print_stage(4, 8, "use persisted communities", verbose)
                persisted_documents = persisted_diagnostics["documents"]
                _write_json_artifact(_artifact_path(current_dir, "relation_evidence.json"), {
                    "documents": {
                        document_id: {
                            "raw_evidence": details["raw_evidence"],
                            "active_evidence": details["active_evidence"],
                            "counts": {
                                "raw_evidence_count": details["diagnostics"].get(
                                    "raw_evidence_count", len(details["raw_evidence"])
                                ),
                                "active_evidence_count": details["diagnostics"].get(
                                    "active_evidence_count", len(details["active_evidence"])
                                ),
                                "relation_status_counts": details["diagnostics"].get(
                                    "relation_status_counts", {}
                                ),
                            },
                        }
                        for document_id, details in sorted(persisted_documents.items())
                    },
                })
                _write_json_artifact(_artifact_path(current_dir, "entity_canonicalization.json"), {
                    "documents": {
                        document_id: details["diagnostics"].get("canonicalization", {})
                        for document_id, details in sorted(persisted_documents.items())
                    },
                })
                _write_json_artifact(_artifact_path(current_dir, "orphan_node_report.json"), {
                    "documents": {
                        document_id: _with_current_query_protection(
                            details["diagnostics"].get("entity_support", {}),
                            details["diagnostics"].get("canonicalization", {}),
                            retrieved_chunks,
                        )
                        for document_id, details in sorted(persisted_documents.items())
                    },
                })
                # This is immutable ingest diagnostics.  Unlike entity support,
                # it has no query-time protection overlay or other mutation.
                _write_json_artifact(_artifact_path(current_dir, "relation_recovery.json"), {
                    "documents": {
                        document_id: details["diagnostics"].get(
                            "relation_recovery", _empty_relation_recovery_diagnostics()
                        )
                        for document_id, details in sorted(persisted_documents.items())
                    },
                })
                community_selection = {
                    "documents": {
                        document_id: details["diagnostics"].get(
                            "community_selection", {}
                        )
                        for document_id, details in sorted(persisted_documents.items())
                    },
                }
                embedding_comparison = {
                    "documents": {
                        document_id: details["diagnostics"].get(
                            "embedding_cluster_comparison", {}
                        )
                        for document_id, details in sorted(persisted_documents.items())
                    },
                }

            _write_json_artifact(
                _artifact_path(current_dir, "community_selection.json"),
                community_selection,
            )
            _write_json_artifact(
                _artifact_path(current_dir, "embedding_cluster_comparison.json"),
                embedding_comparison,
            )

            _print_stage(5, 8, "rank graph and prune context", verbose, [
                f"Communities: {len(communities)}",
                f"Modularity: {modularity:.4f}",
            ])
            ranked = analyzer.analyze(G)
            analyzer.save_ranked_csv(ranked, _artifact_path(current_dir, "graph_ranked_nodes.csv"))
            analyzer.save_ranked_json(ranked, _artifact_path(current_dir, "graph_ranked_nodes.json"))
            relation_extraction_mode = getattr(extractor, "relation_extraction_mode", "unavailable")
            analyzer.save_summary_json(ranked, communities, modularity, _artifact_path(current_dir, "graph_summary.json"), relation_extraction_mode=relation_extraction_mode, graph=G)

            print(f"\n  Communities : {len(communities)}")
            print(f"  Modularity  : {modularity:.4f}")

            try:
                pruned_result = pruner.select_top_chunks(ranked, retrieved_chunks, graph=G)
            except TypeError:
                pruned_result = pruner.select_top_chunks(ranked, retrieved_chunks)
            context_allocation = _context_allocation_artifact(
                pruned_result,
                graph_source=context_graph_source,
                fallback_status=context_fallback_status,
                fallback_reason=context_fallback_reason,
                query_protected_chunk_uids=query_protected_chunk_uids,
                attempt=attempt,
            )
            _write_json_artifact(
                _artifact_path(current_dir, "context_allocation.json"),
                context_allocation,
            )
            pruner.save_pruned_json(pruned_result, _artifact_path(current_dir, "pruned_summary_context.json"))
            pruner.save_pruned_csv(pruned_result, _artifact_path(current_dir, "pruned_summary_context.csv"))
            next_stage = "prompt"

        if next_stage == "prompt":
            _print_stage(6, 8, "summarize communities", verbose)
            community_prompts = prompt_builder.build_all_community_prompts(pruned_result, query=query, style="concise")
            prompt_delivery = _prompt_delivery_diagnostics(community_prompts)
            if prompt_delivery:
                context_allocation["prompt_delivery"] = prompt_delivery
                _write_json_artifact(
                    _artifact_path(current_dir, "context_allocation.json"),
                    context_allocation,
                )
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
            selected_evidence = _evaluation_source_chunks(pruned_result, retrieved_chunks)
            try:
                eval_result = evaluator.evaluate_without_reference(
                    generated_summary=final_result["final_summary"],
                    source_chunks=selected_evidence,
                    query=query,
                )
            except TypeError:
                eval_result = evaluator.evaluate_without_reference(
                    generated_summary=final_result["final_summary"],
                    source_chunks=selected_evidence,
                )
            evaluator.save_evaluation_json(eval_result, _artifact_path(current_dir, "evaluation_result.json"))

            quality_result = checker.check(eval_result)
            action_result = checker.suggest_action(quality_result)
            if forced_retry_stage and attempt == 0:
                forced_failure = {
                    "stage": forced_retry_stage,
                    "attempt": attempt,
                    "test_only": True,
                }
                quality_result = {
                    **quality_result,
                    "status": "FAIL",
                    "passed": False,
                    "forced_failure": forced_failure,
                }
                action_result = {
                    **action_result,
                    "action": f"retry_{forced_retry_stage}",
                    "reason": "Test-only forced feedback retry",
                    "forced_failure": forced_failure,
                }
            checker.save_quality_report(quality_result, action_result, _artifact_path(current_dir, "quality_gate_report.json"))

            print(f"\n  Quality Status  : {quality_result['status']}")
            print(f"  Suggested Action: {action_result['action']}")

            decision = {
                **controller.decide(
                    quality_result=quality_result,
                    action_result=action_result,
                    retry_state=retry_state,
                ),
                "attempt": attempt,
            }
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
