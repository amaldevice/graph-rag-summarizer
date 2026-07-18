"""Deterministic, bounded cross-chunk relation-candidate generation.

This module deliberately produces diagnostic candidates only.  It neither adds
edges nor modifies any graph attribute; verification owns promotion to active
relation evidence.
"""

from __future__ import annotations

import json
import math
import inspect
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from graph.relation_evidence import canonicalize_entities


_HIERARCHY_FIELDS = (
    "section",
    "section_id",
    "parent_chunk_uid",
    "parent_chunk_id",
    "parent_id",
    "path",
)
_PARENT_FIELDS = ("parent_chunk_uid", "parent_chunk_id")
_LABEL_ALIASES = {
    "organization": "org",
    "company": "org",
    "institution": "org",
    "location": "loc",
    "geopolitical_entity": "gpe",
    "facility": "fac",
}
_VERIFICATION_FIELDS = {"status", "relation", "confidence", "support_chunk_uids"}
_VERIFICATION_STATUSES = {"accepted", "rejected", "insufficient"}
_MAX_EVIDENCE_CHUNKS = 8
_MAX_EVIDENCE_CHARS = 600
_MAX_EVIDENCE_RELATIONS = 8


def _json_records(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Copy and canonically order diagnostic records without graph mutation."""
    return [dict(value) for value in sorted(values, key=_stable_key)]


def _stable_key(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _string_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Iterable) and not isinstance(value, Mapping):
        return [str(item) for item in value if item is not None and str(item)]
    return [str(value)]


def _nonnegative_cap(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _chunk_order(chunk: Mapping[str, Any]) -> tuple[int, Any, str]:
    """Use a document position when supplied, with the UID as a stable tie-break."""
    value = chunk.get("chunk_id")
    if value is None:
        hierarchy = chunk.get("hierarchy")
        if isinstance(hierarchy, Mapping):
            value = hierarchy.get("sentence_index", hierarchy.get("paragraph_id"))
    try:
        return (0, int(value), str(chunk["chunk_uid"]))
    except (TypeError, ValueError, KeyError):
        return (1, str(value), str(chunk.get("chunk_uid", "")))


def _chunk_ref_candidates(
    value: Any,
    *,
    document_id: str | None,
    by_uid: Mapping[str, list[tuple[str, str]]],
    by_chunk_id: Mapping[str, list[tuple[str, str]]],
) -> list[tuple[str, str]]:
    """Resolve one reference without ever guessing between documents."""
    candidates = list(by_uid.get(str(value), ()))
    if not candidates:
        candidates = list(by_chunk_id.get(str(value), ()))
    if document_id is not None:
        matching = [candidate for candidate in candidates if candidate[0] == document_id]
        return matching
    return candidates if len(candidates) == 1 else []


def _entity_chunk_keys(
    entity: Mapping[str, Any],
    *,
    by_uid: Mapping[str, list[tuple[str, str]]],
    by_chunk_id: Mapping[str, list[tuple[str, str]]],
) -> set[tuple[str, str]]:
    document_id = entity.get("document_id")
    normalized_document_id = str(document_id) if document_id is not None else None
    values: list[Any] = []
    for field in ("chunk_uid", "chunk_uids", "chunk_id", "chunk_ids"):
        values.extend(_string_values(entity.get(field)))
    keys: set[tuple[str, str]] = set()
    for value in values:
        keys.update(_chunk_ref_candidates(
            value,
            document_id=normalized_document_id,
            by_uid=by_uid,
            by_chunk_id=by_chunk_id,
        ))
    return keys


def _entity_label(entity: Mapping[str, Any]) -> str:
    for field in ("label", "type", "entity_type"):
        value = entity.get(field)
        if value not in (None, ""):
            normalized = str(value).strip().casefold()
            return _LABEL_ALIASES.get(normalized, normalized)
    return ""


def _labels_compatible(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Avoid cross-type speculation while retaining legacy entities without labels."""
    left_label = left.get("label", "")
    right_label = right.get("label", "")
    return not left_label or not right_label or left_label == right_label


def _graph_chunk_nodes(
    graph: Any,
    *,
    by_uid: Mapping[str, list[tuple[str, str]]],
    by_chunk_id: Mapping[str, list[tuple[str, str]]],
) -> tuple[dict[Any, tuple[str, str]], dict[Any, Mapping[str, Any]]]:
    """Map graph chunk nodes back to document-local chunk IDs without mutation."""
    if graph is None:
        return {}, {}
    try:
        graph_nodes = list(graph.nodes(data=True))
    except (AttributeError, TypeError, ValueError):
        return {}, {}

    mapped: dict[Any, tuple[str, str]] = {}
    attributes: dict[Any, Mapping[str, Any]] = {}
    for node, raw_attributes in graph_nodes:
        attrs = raw_attributes if isinstance(raw_attributes, Mapping) else {}
        attributes[node] = attrs
        document_id = attrs.get("document_id")
        normalized_document_id = str(document_id) if document_id is not None else None
        values = _string_values(attrs.get("chunk_uid"))
        if not values:
            values = _string_values(node)
            if isinstance(node, str) and node.startswith("chunk_"):
                values.append(node[len("chunk_"):])
        for value in values:
            candidates = _chunk_ref_candidates(
                value,
                document_id=normalized_document_id,
                by_uid=by_uid,
                by_chunk_id=by_chunk_id,
            )
            if len(candidates) == 1:
                mapped[node] = candidates[0]
                break
    return mapped, attributes


def _adjacent_pairs(
    chunk_keys: Iterable[tuple[str, str]],
    chunk_records: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    ordered = sorted(set(chunk_keys), key=lambda key: _chunk_order(chunk_records[key]))
    return list(zip(ordered, ordered[1:]))


def _candidate_sort_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    # Recovery candidates are considered first, but the remaining ordering is
    # entirely lexical and therefore independent of input iteration order.
    return (
        0 if "weak_orphan_recovery" in candidate["triggers"] else 1,
        candidate.get("document_id", ""),
        candidate["head_canonical_id"],
        candidate["tail_canonical_id"],
        tuple(candidate["support_chunk_uids"]),
    )


def _budget_rejection(
    candidate: Mapping[str, Any],
    reason: str,
    limit: int,
    **details: Any,
) -> dict[str, Any]:
    return {"candidate": dict(candidate), "reason": reason, "limit": limit, **details}


def generate_relation_candidates(
    chunks: Iterable[Mapping[str, Any]],
    entities: Iterable[Mapping[str, Any]],
    graph: Any,
    support_report: Mapping[str, Any] | None,
    *,
    per_neighborhood_cap: int = 16,
    per_entity_cap: int = 4,
    per_chunk_cap: int = 6,
    total_cap: int = 24,
) -> dict[str, list[dict[str, Any]]]:
    """Return bounded, document-local *pending* cross-chunk relation candidates.

    The policy constructs chunk neighborhoods only from graph semantic/shared
    edges, repeated canonical mentions, and immediate hierarchy adjacency.  It
    then forms compatible entity pairs *inside* those neighborhoods.  No graph
    operation mutates ``graph`` and no document-wide entity-pair scan occurs.
    """
    chunk_candidates: list[dict[str, Any]] = []
    for raw_chunk in chunks:
        if not isinstance(raw_chunk, Mapping) or raw_chunk.get("context_only"):
            continue
        chunk_uid = raw_chunk.get("chunk_uid", raw_chunk.get("chunk_id"))
        if chunk_uid is None or not str(chunk_uid):
            continue
        chunk = dict(raw_chunk)
        chunk["chunk_uid"] = str(chunk_uid)
        chunk["document_id"] = str(chunk.get("document_id", ""))
        chunk_candidates.append(chunk)

    chunk_records: dict[tuple[str, str], dict[str, Any]] = {}
    for chunk in sorted(chunk_candidates, key=_stable_key):
        chunk_records.setdefault((chunk["document_id"], chunk["chunk_uid"]), chunk)
    by_uid: dict[str, list[tuple[str, str]]] = defaultdict(list)
    by_chunk_id: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key, chunk in chunk_records.items():
        by_uid[key[1]].append(key)
        if chunk.get("chunk_id") is not None:
            by_chunk_id[str(chunk["chunk_id"])].append(key)
    for index in (by_uid, by_chunk_id):
        for values in index.values():
            values.sort()

    # Aggregate mentions by canonical entity within a document.  Canonical
    # entities may legitimately occur in several chunks; their chunk list is
    # later used as a bounded, adjacent identity neighborhood.
    entity_records: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_entity in sorted(
        (entity for entity in entities if isinstance(entity, Mapping)), key=_stable_key
    ):
        entity = dict(raw_entity)
        canonical_id = entity.get("canonical_id")
        canonical_text = entity.get("canonical_text")
        if not canonical_id or canonical_text in (None, ""):
            canonicalized, _ = canonicalize_entities([entity])
            if not canonicalized:
                continue
            normalized = canonicalized[0]
            canonical_id = canonical_id or normalized["canonical_id"]
            canonical_text = canonical_text or normalized["canonical_text"]
        if not str(canonical_id) or canonical_text is None or not str(canonical_text):
            continue
        chunk_keys = _entity_chunk_keys(entity, by_uid=by_uid, by_chunk_id=by_chunk_id)
        for document_id, chunk_uid in sorted(chunk_keys):
            key = (document_id, str(canonical_id))
            record = entity_records.setdefault(key, {
                "canonical_id": str(canonical_id),
                "canonical_texts": set(),
                "labels": set(),
                "chunk_keys": set(),
            })
            record["canonical_texts"].add(str(canonical_text))
            label = _entity_label(entity)
            if label:
                record["labels"].add(label)
            record["chunk_keys"].add((document_id, chunk_uid))

    entities_by_chunk: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for (document_id, canonical_id), record in sorted(entity_records.items()):
        entity = {
            "canonical_id": canonical_id,
            "canonical_text": sorted(record["canonical_texts"], key=lambda text: (text.casefold(), text))[0],
            "label": sorted(record["labels"])[0] if record["labels"] else "",
        }
        for chunk_key in sorted(record["chunk_keys"]):
            entities_by_chunk[chunk_key].append(entity)
    for chunk_entities in entities_by_chunk.values():
        chunk_entities.sort(key=lambda entity: entity["canonical_id"])

    # Every neighborhood entry is a pair of document-local chunks plus all
    # reasons why that pair was boundedly considered.
    neighborhoods: dict[tuple[str, str, str], set[str]] = defaultdict(set)

    def add_neighborhood(left: tuple[str, str], right: tuple[str, str], trigger: str) -> None:
        if left == right or left[0] != right[0]:
            return
        if left not in chunk_records or right not in chunk_records:
            return
        first_uid, second_uid = sorted((left[1], right[1]))
        neighborhoods[(left[0], first_uid, second_uid)].add(trigger)

    graph_nodes, graph_attributes = _graph_chunk_nodes(
        graph, by_uid=by_uid, by_chunk_id=by_chunk_id
    )
    if graph is not None:
        try:
            graph_edges = graph.edges(data=True)
        except (AttributeError, TypeError, ValueError):
            graph_edges = ()
        for edge in graph_edges:
            if len(edge) < 3:
                continue
            left_node, right_node, attrs = edge[0], edge[1], edge[-1]
            if not isinstance(attrs, Mapping) or attrs.get("edge_type") != "knn_similarity":
                continue
            left = graph_nodes.get(left_node)
            right = graph_nodes.get(right_node)
            if left is not None and right is not None:
                add_neighborhood(left, right, "semantic_neighbor")

        # A shared *entity* graph neighbor is bounded by the graph adjacency,
        # and only adjacent chunk occurrences are paired to avoid a clique for
        # entities mentioned throughout a long document.
        shared_neighbors: dict[Any, set[tuple[str, str]]] = defaultdict(set)
        try:
            graph_neighbors = graph.neighbors
        except AttributeError:
            graph_neighbors = None
        if callable(graph_neighbors):
            for node, chunk_key in graph_nodes.items():
                try:
                    neighbors = list(graph_neighbors(node))
                except (TypeError, ValueError):
                    continue
                for neighbor in neighbors:
                    if neighbor in graph_nodes:
                        continue
                    attrs = graph_attributes.get(neighbor, {})
                    node_type = attrs.get("type") if isinstance(attrs, Mapping) else None
                    if node_type not in (None, "entity") and not str(neighbor).startswith("ent_"):
                        continue
                    if node_type == "entity" or str(neighbor).startswith("ent_"):
                        shared_neighbors[neighbor].add(chunk_key)
        for chunk_keys in shared_neighbors.values():
            for left, right in _adjacent_pairs(chunk_keys, chunk_records):
                add_neighborhood(left, right, "shared_graph_neighbor")

    # Repeated canonical mentions provide a second, graph-independent bounded
    # neighborhood.  As above, retain only adjacent mention locations.
    for record in entity_records.values():
        for left, right in _adjacent_pairs(record["chunk_keys"], chunk_records):
            add_neighborhood(left, right, "canonical_identity")

    # Hierarchy groups similarly use immediate document neighbors rather than
    # the full same-section clique.  Direct parent references are also a local
    # hierarchy adjacency when both chunks are part of the input document.
    hierarchy_groups: dict[tuple[str, str, str], set[tuple[str, str]]] = defaultdict(set)
    for chunk_key, chunk in chunk_records.items():
        hierarchy = chunk.get("hierarchy")
        hierarchy = hierarchy if isinstance(hierarchy, Mapping) else {}
        values = {"section": chunk.get("section")}
        values.update({field: hierarchy.get(field) for field in _HIERARCHY_FIELDS})
        for field, value in values.items():
            if value in (None, ""):
                continue
            hierarchy_groups[(chunk_key[0], field, _stable_key(value))].add(chunk_key)
        for field in _PARENT_FIELDS:
            value = hierarchy.get(field)
            if value in (None, ""):
                continue
            for parent_key in _chunk_ref_candidates(
                value,
                document_id=chunk_key[0],
                by_uid=by_uid,
                by_chunk_id=by_chunk_id,
            ):
                add_neighborhood(chunk_key, parent_key, "hierarchy_adjacency")
    for chunk_keys in hierarchy_groups.values():
        for left, right in _adjacent_pairs(chunk_keys, chunk_records):
            add_neighborhood(left, right, "hierarchy_adjacency")

    report = support_report if isinstance(support_report, Mapping) else {}
    weak_orphan_ids: set[str] = set()
    for field in ("weakly_supported", "mention_only", "isolated_noise_candidates"):
        weak_orphan_ids.update(_string_values(report.get(field)))
    for element in _string_values(report.get("relation_orphans")):
        weak_orphan_ids.add(element)
    raw_elements = report.get("elements", ())
    if isinstance(raw_elements, Iterable) and not isinstance(raw_elements, (str, Mapping)):
        for element in raw_elements:
            if not isinstance(element, Mapping):
                continue
            if element.get("support") in {"weakly_supported", "mention_only"} or element.get("isolated_noise_candidate"):
                if element.get("canonical_id") is not None:
                    weak_orphan_ids.add(str(element["canonical_id"]))
    raw_orphans = report.get("relation_orphans", ())
    if isinstance(raw_orphans, Iterable) and not isinstance(raw_orphans, (str, Mapping)):
        for orphan in raw_orphans:
            if isinstance(orphan, Mapping) and orphan.get("canonical_id") is not None:
                weak_orphan_ids.add(str(orphan["canonical_id"]))
    weak_orphan_chunks = {
        chunk_key
        for chunk_key, chunk_entities in entities_by_chunk.items()
        if any(entity["canonical_id"] in weak_orphan_ids for entity in chunk_entities)
    }

    # Build all candidate provenance before caps so that an accepted candidate
    # contains the merged support chunks and trigger set of its duplicate paths.
    candidates: dict[tuple[str, str, str], dict[str, Any]] = {}
    deduplicated: list[dict[str, Any]] = []
    budget_rejected: list[dict[str, Any]] = []
    region_cap = _nonnegative_cap(per_neighborhood_cap)
    for (document_id, left_uid, right_uid), neighborhood_triggers in sorted(neighborhoods.items()):
        left_key = (document_id, left_uid)
        right_key = (document_id, right_uid)
        region_count = 0
        for left in entities_by_chunk.get(left_key, ()):
            for right in entities_by_chunk.get(right_key, ()):
                if left["canonical_id"] == right["canonical_id"] or not _labels_compatible(left, right):
                    continue
                # Recovery starts from a weak/orphan region.  A semantic or
                # hierarchy edge alone is not enough to reopen an otherwise
                # strongly supported portion of the graph.
                if left_key not in weak_orphan_chunks and right_key not in weak_orphan_chunks:
                    continue
                head, tail = sorted((left, right), key=lambda entity: entity["canonical_id"])
                key = (document_id, head["canonical_id"], tail["canonical_id"])
                occurrence_triggers = set(neighborhood_triggers)
                occurrence_triggers.add("compatible_entity_label")
                occurrence_triggers.add("weak_orphan_recovery")
                support_chunk_uids = sorted((left_uid, right_uid))
                if region_count >= region_cap:
                    budget_rejected.append(_budget_rejection({
                        "document_id": document_id,
                        "head_canonical_id": head["canonical_id"],
                        "tail_canonical_id": tail["canonical_id"],
                        "support_chunk_uids": support_chunk_uids,
                    }, "per_neighborhood_cap", region_cap))
                    continue
                region_count += 1
                if key in candidates:
                    deduplicated.append({
                        "document_id": document_id,
                        "head_canonical_id": head["canonical_id"],
                        "tail_canonical_id": tail["canonical_id"],
                        "support_chunk_uids": support_chunk_uids,
                        "triggers": sorted(occurrence_triggers),
                        "duplicate_of": {
                            "head_canonical_id": head["canonical_id"],
                            "tail_canonical_id": tail["canonical_id"],
                        },
                    })
                    candidates[key]["support_chunk_uids"] = sorted(
                        set(candidates[key]["support_chunk_uids"]).union(support_chunk_uids)
                    )
                    candidates[key]["triggers"] = sorted(
                        set(candidates[key]["triggers"]).union(occurrence_triggers)
                    )
                    continue
                candidates[key] = {
                    "document_id": document_id,
                    "head": head["canonical_text"],
                    "tail": tail["canonical_text"],
                    "head_canonical_id": head["canonical_id"],
                    "head_text": head["canonical_text"],
                    "tail_canonical_id": tail["canonical_id"],
                    "tail_text": tail["canonical_text"],
                    "support_chunk_uids": support_chunk_uids,
                    "triggers": sorted(occurrence_triggers),
                    "scope": "cross_chunk",
                    "status": "pending",
                    "verification_state": "pending",
                }

    entity_cap = _nonnegative_cap(per_entity_cap)
    chunk_cap = _nonnegative_cap(per_chunk_cap)
    run_cap = _nonnegative_cap(total_cap)
    generated: list[dict[str, Any]] = []
    entity_counts: dict[tuple[str, str], int] = defaultdict(int)
    chunk_counts: dict[tuple[str, str], int] = defaultdict(int)
    for candidate in sorted(candidates.values(), key=_candidate_sort_key):
        endpoint_ids = (candidate["head_canonical_id"], candidate["tail_canonical_id"])
        blocked_entities = [
            entity_id
            for entity_id in endpoint_ids
            if entity_counts[(candidate["document_id"], entity_id)] >= entity_cap
        ]
        if blocked_entities:
            budget_rejected.append(_budget_rejection(
                candidate, "per_entity_cap", entity_cap, entity_ids=blocked_entities
            ))
            continue
        candidate_chunk_keys = [
            (candidate["document_id"], chunk_uid)
            for chunk_uid in candidate["support_chunk_uids"]
        ]
        blocked_chunks = [
            chunk_uid for chunk_uid, key in zip(candidate["support_chunk_uids"], candidate_chunk_keys)
            if chunk_counts[key] >= chunk_cap
        ]
        if blocked_chunks:
            budget_rejected.append(_budget_rejection(
                candidate, "per_chunk_cap", chunk_cap, chunk_uids=blocked_chunks
            ))
            continue
        if len(generated) >= run_cap:
            budget_rejected.append(_budget_rejection(candidate, "total_cap", run_cap))
            continue
        generated.append(candidate)
        for entity_id in endpoint_ids:
            entity_counts[(candidate["document_id"], entity_id)] += 1
        for chunk_key in candidate_chunk_keys:
            chunk_counts[chunk_key] += 1

    return {
        "generated": generated,
        "deduplicated": sorted(deduplicated, key=_stable_key),
        "budget_rejected": budget_rejected,
    }


def _provider_is_available(provider: Any) -> bool:
    """Avoid an optional provider call when its shared fallback chain is empty."""
    if provider is None or not callable(getattr(provider, "call_llm", None)):
        return False
    has_available_provider = getattr(provider, "has_available_provider", None)
    if callable(has_available_provider):
        try:
            return bool(has_available_provider())
        except (KeyError, TypeError, ValueError, RuntimeError):
            return False
    resolve_chain = getattr(provider, "resolve_chain", None)
    if not callable(resolve_chain):
        return True
    try:
        return bool(resolve_chain())
    except (KeyError, TypeError, ValueError, RuntimeError):
        return False


def _provider_supports_response_validator(provider: Any) -> bool:
    """Keep the recovery seam compatible with legacy two-argument fakes."""
    call_llm = getattr(provider, "call_llm", None)
    if not callable(call_llm):
        return False
    try:
        parameters = inspect.signature(call_llm).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.name == "response_validator"
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )


def _chunk_uid_for_graph_node(graph: Any, chunks_by_uid: Mapping[str, Mapping[str, Any]]) -> dict[Any, str]:
    """Return the local chunk UID for graph nodes that expose one explicitly."""
    try:
        nodes = graph.nodes(data=True)
    except (AttributeError, TypeError, ValueError):
        return {}
    mapped: dict[Any, str] = {}
    for node, attributes in nodes:
        attrs = attributes if isinstance(attributes, Mapping) else {}
        chunk_uid = attrs.get("chunk_uid")
        if chunk_uid is not None and str(chunk_uid) in chunks_by_uid:
            mapped[node] = str(chunk_uid)
    return mapped


def _bounded_evidence_window(
    candidate: Mapping[str, Any],
    chunks: Iterable[Mapping[str, Any]],
    graph: Any,
    raw_evidence: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a fixed-size verifier context, never a document-wide prompt."""
    chunks_by_uid = {
        str(chunk.get("chunk_uid", chunk.get("chunk_id"))): chunk
        for chunk in chunks
        if isinstance(chunk, Mapping)
        and chunk.get("chunk_uid", chunk.get("chunk_id")) is not None
    }
    selected_uids = {
        str(chunk_uid)
        for chunk_uid in candidate.get("support_chunk_uids", ())
        if str(chunk_uid) in chunks_by_uid
    }
    graph_nodes = _chunk_uid_for_graph_node(graph, chunks_by_uid)
    try:
        graph_edges = graph.edges(data=True)
    except (AttributeError, TypeError, ValueError):
        graph_edges = ()
    semantic_neighbors: set[str] = set()
    for edge in graph_edges:
        if len(edge) < 3:
            continue
        left, right, attributes = edge[0], edge[1], edge[-1]
        if not isinstance(attributes, Mapping) or attributes.get("edge_type") != "knn_similarity":
            continue
        left_uid = graph_nodes.get(left)
        right_uid = graph_nodes.get(right)
        if left_uid in selected_uids and right_uid is not None:
            semantic_neighbors.add(right_uid)
        if right_uid in selected_uids and left_uid is not None:
            semantic_neighbors.add(left_uid)

    ordered_uids = sorted(selected_uids)
    for chunk_uid in sorted(semantic_neighbors):
        if len(ordered_uids) >= _MAX_EVIDENCE_CHUNKS:
            break
        if chunk_uid not in selected_uids:
            ordered_uids.append(chunk_uid)

    records = []
    for chunk_uid in ordered_uids:
        chunk = chunks_by_uid[chunk_uid]
        records.append({
            "chunk_uid": chunk_uid,
            "hierarchy": chunk.get("hierarchy") or {},
            "text": str(chunk.get("text", ""))[:_MAX_EVIDENCE_CHARS],
        })

    selected_set = set(ordered_uids)
    relevant_relations = []
    for relation in raw_evidence:
        if not isinstance(relation, Mapping):
            continue
        support = set(_string_values(relation.get("support_chunk_uids")))
        if support.intersection(selected_set):
            relevant_relations.append({
                key: relation.get(key)
                for key in ("head", "relation", "tail", "source", "status", "support_chunk_uids")
                if key in relation
            })
    return {
        "chunk_uids": ordered_uids,
        "chunks": records,
        "raw_evidence": _json_records(relevant_relations)[:_MAX_EVIDENCE_RELATIONS],
    }


def _verification_prompt(candidate: Mapping[str, Any], window: Mapping[str, Any]) -> str:
    """Render the bounded verification request with one strict response shape."""
    evidence = json.dumps(window, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return (
        "Verify whether the candidate entities have a relation supported only by the "
        "bounded evidence below. Return JSON only, with exactly these fields: "
        "status, relation, confidence, support_chunk_uids. status must be accepted, "
        "rejected, or insufficient. For accepted, relation is a non-empty string, "
        "confidence is a number from 0 to 1, and support_chunk_uids is a non-empty "
        "subset of the supplied chunk_uids. For rejected or insufficient, use null "
        "for relation and confidence and [] for support_chunk_uids. Do not infer facts.\n"
        f"Candidate: {json.dumps({'head': candidate['head_text'], 'tail': candidate['tail_text']}, ensure_ascii=False, separators=(',', ':'), sort_keys=True)}\n"
        f"Evidence: {evidence}"
    )


def _invalid_verification(reason: str) -> tuple[str, dict[str, Any] | None, str]:
    return "insufficient", None, reason


def _parse_verification_response(
    content: Any,
    candidate: Mapping[str, Any],
    window: Mapping[str, Any],
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Accept only a schema-valid provider decision tied to the bounded window."""
    if not isinstance(content, (str, bytes, bytearray)):
        return _invalid_verification("malformed_response")
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return _invalid_verification("malformed_response")
    if not isinstance(payload, Mapping) or set(payload) != _VERIFICATION_FIELDS:
        return _invalid_verification("malformed_schema")
    status = payload.get("status")
    if status not in _VERIFICATION_STATUSES:
        return _invalid_verification("invalid_status")

    relation = payload.get("relation")
    confidence = payload.get("confidence")
    support_chunk_uids = payload.get("support_chunk_uids")
    if not isinstance(support_chunk_uids, list) or any(
        not isinstance(chunk_uid, str) or not chunk_uid for chunk_uid in support_chunk_uids
    ):
        return _invalid_verification("invalid_support_chunk_uids")
    if len(set(support_chunk_uids)) != len(support_chunk_uids):
        return _invalid_verification("invalid_support_chunk_uids")

    if status != "accepted":
        if relation is not None or confidence is not None or support_chunk_uids:
            return _invalid_verification("malformed_nonacceptance")
        return status, None, None

    if not isinstance(relation, str) or not relation.strip():
        return _invalid_verification("invalid_relation")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return _invalid_verification("invalid_confidence")
    numeric_confidence = float(confidence)
    if not math.isfinite(numeric_confidence) or not 0 <= numeric_confidence <= 1:
        return _invalid_verification("invalid_confidence")
    available_uids = set(window.get("chunk_uids", ()))
    if not support_chunk_uids or not set(support_chunk_uids).issubset(available_uids):
        return _invalid_verification("unsupported_chunk_uids")
    return "accepted", {
        "relation": relation.strip(),
        "confidence": numeric_confidence,
        "support_chunk_uids": sorted(support_chunk_uids),
    }, None


def _candidate_evidence(
    candidate: Mapping[str, Any],
    *,
    status: str,
    provider: str,
    accepted: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep every recovery decision in raw evidence; only accepted is active."""
    evidence = {
        "head": candidate["head_text"],
        "tail": candidate["tail_text"],
        "relation": None,
        "source": provider,
        "scope": "cross_chunk",
        "support_chunk_uids": list(candidate["support_chunk_uids"]),
        "candidate_triggers": list(candidate["triggers"]),
        "candidate_status": candidate["status"],
        "status": status,
        "verification_state": "verified" if status == "accepted" else status,
        "evidence_type": "verified" if status == "accepted" else "unverified",
    }
    if accepted is not None:
        evidence.update(accepted)
    return evidence


def verify_relation_candidates(
    candidates: Iterable[Mapping[str, Any]],
    chunks: Iterable[Mapping[str, Any]],
    graph: Any,
    raw_evidence: Iterable[Mapping[str, Any]],
    provider: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Verify bounded candidates through the existing shared provider router.

    A router owns its sequential fallback chain.  This function asks it at most
    once per generated candidate and treats provider absence, malformed output,
    and exhausted fallback as diagnostic evidence rather than an ingest error.
    """
    ordered_candidates = [dict(candidate) for candidate in candidates]
    decisions: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    if not _provider_is_available(provider):
        for candidate in ordered_candidates:
            decision = {
                "candidate": candidate,
                "status": "unavailable",
                "reason": "provider_unavailable",
                "attempted": False,
            }
            decisions.append(decision)
            evidence.append(_candidate_evidence(
                candidate, status="unavailable", provider="provider-router"
            ))
        return evidence, decisions

    provider_failed = False
    for candidate in ordered_candidates:
        if provider_failed:
            decision = {
                "candidate": candidate,
                "status": "unavailable",
                "reason": "provider_unavailable_after_failure",
                "attempted": False,
            }
            decisions.append(decision)
            evidence.append(_candidate_evidence(
                candidate, status="unavailable", provider="provider-router"
            ))
            continue

        window = _bounded_evidence_window(candidate, chunks, graph, raw_evidence)
        system_prompt = "You verify cross-chunk relations as strict JSON."
        prompt = _verification_prompt(candidate, window)
        try:
            if _provider_supports_response_validator(provider):
                content = provider.call_llm(
                    system_prompt,
                    prompt,
                    response_validator=lambda response: _parse_verification_response(
                        response, candidate, window
                    )[2] is None,
                )
            else:
                content = provider.call_llm(system_prompt, prompt)
        except Exception:
            provider_failed = True
            decision = {
                "candidate": candidate,
                "status": "unavailable",
                "reason": "provider_call_failed",
                "attempted": True,
                "evidence_window": window,
            }
            decisions.append(decision)
            evidence.append(_candidate_evidence(
                candidate, status="unavailable", provider="provider-router"
            ))
            continue

        status, accepted, reason = _parse_verification_response(content, candidate, window)
        provider_name = str(getattr(provider, "active_provider", None) or "provider-router")
        decision = {
            "candidate": candidate,
            "status": status,
            "attempted": True,
            "provider": provider_name,
            "evidence_window": window,
        }
        if reason is not None:
            decision["reason"] = reason
        decisions.append(decision)
        evidence.append(_candidate_evidence(
            candidate,
            status=status,
            provider=provider_name,
            accepted=accepted,
        ))
    return evidence, decisions


def cleanup_unsupported_entity_nodes(graph: Any, support_report: Mapping[str, Any]) -> dict[str, Any]:
    """Remove only unprotected isolated-noise *entity* nodes after recovery."""
    result = {"removed_entity_ids": [], "removed": [], "preserved": []}
    if graph is None or not isinstance(support_report, Mapping):
        return result
    elements = support_report.get("elements", ())
    if not isinstance(elements, Iterable) or isinstance(elements, (str, Mapping)):
        return result
    for element in sorted(
        (item for item in elements if isinstance(item, Mapping)), key=_stable_key
    ):
        canonical_id = element.get("canonical_id")
        if not element.get("isolated_noise_candidate") or canonical_id is None:
            continue
        canonical_id = str(canonical_id)
        if element.get("query_protected"):
            result["preserved"].append({
                "canonical_id": canonical_id,
                "reason": "query_protected",
            })
            continue
        try:
            attributes = graph.nodes[canonical_id]
        except (KeyError, TypeError, AttributeError):
            result["preserved"].append({
                "canonical_id": canonical_id,
                "reason": "not_in_graph",
            })
            continue
        if attributes.get("type") != "entity":
            result["preserved"].append({
                "canonical_id": canonical_id,
                "reason": "not_entity_node",
            })
            continue
        graph.remove_node(canonical_id)
        result["removed_entity_ids"].append(canonical_id)
        result["removed"].append({
            "canonical_id": canonical_id,
            "reason": "isolated_noise_candidate",
        })
    return result
