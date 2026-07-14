"""Deterministic, backward-compatible relation evidence normalization."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any


_WEIGHTS = {
    "verified": 1.0,
    "explicit": 1.0,
    "same_sentence": 0.6,
    "nearby_window": 0.4,
    "same_chunk": 0.2,
}
_WEAK_SOURCES = {"rule-based", "fallback"}
_ACTIVE_EVIDENCE_TYPES = {"explicit", "verified"}
_CANONICAL_SEPARATORS = re.compile(r"[,.;:()\[\]{}_-]+")
_WHITESPACE = re.compile(r"\s+")


def _support_chunk_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value if item is not None and str(item)]
    return [str(value)]


def _clamp_confidence(value: Any, default: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(confidence):
        return default
    return min(1.0, max(0.0, confidence))


def _sort_key(record: Mapping[str, Any]) -> str:
    return json.dumps(record, default=str, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def normalize_relation_evidence(
    records: Iterable[Mapping[str, Any]],
    *,
    support_chunk_uid: str | None = None,
) -> list[dict[str, Any]]:
    """Return normalized, deterministically ordered local relation evidence."""
    normalized = []
    for raw_record in records:
        record = dict(raw_record)
        source = record.get("source") or "llm"
        is_weak_source = str(source).casefold() in _WEAK_SOURCES
        evidence_type = record.get("evidence_type") or (
            "same_chunk" if is_weak_source else "explicit"
        )
        resolved_weight = _WEIGHTS.get(evidence_type, 0.0)
        status = record.get("status") or ("unverified" if is_weak_source else "accepted")
        support_ids = _support_chunk_ids(record.get("support_chunk_uids"))
        if support_chunk_uid is not None:
            support_ids.extend(_support_chunk_ids(support_chunk_uid))

        record.update({
            "source": source,
            "scope": record.get("scope") or "local",
            "confidence": _clamp_confidence(record.get("confidence"), resolved_weight),
            "support_chunk_uids": sorted(set(support_ids)),
            "evidence_type": evidence_type,
            "verification_state": record.get("verification_state") or status,
            "status": status,
            "resolved_weight": resolved_weight,
        })
        normalized.append(record)
    return sorted(normalized, key=_sort_key)


def is_active_relation(record: Mapping[str, Any]) -> bool:
    """Return whether evidence may contribute an active relation edge."""
    return (
        record.get("status") == "accepted"
        and record.get("evidence_type") in _ACTIVE_EVIDENCE_TYPES
    )


def canonicalize_entities(
    entities: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Return copied entities and a deterministic, surface-only alias report."""
    canonicalized = []
    grouped: dict[str, dict[str, Any]] = {}
    prepared = []
    labels_by_surface: dict[str, set[str]] = {}

    for raw_entity in entities:
        entity = dict(raw_entity)
        original_mention = entity.get("text", "")
        normalized_text = _WHITESPACE.sub(
            " ", _CANONICAL_SEPARATORS.sub(" ", str(original_mention).casefold())
        ).strip()
        label = next(
            (
                str(entity[field]).strip().casefold()
                for field in ("label", "type", "entity_type")
                if entity.get(field) not in (None, "")
            ),
            "",
        )
        prepared.append((entity, original_mention, normalized_text, label))
        if label:
            labels_by_surface.setdefault(normalized_text, set()).add(label)

    for entity, original_mention, normalized_text, label in prepared:
        canonical_id = f"ent_{normalized_text.replace(' ', '_')}"
        if len(labels_by_surface.get(normalized_text, set())) > 1 and label:
            normalized_label = _WHITESPACE.sub(
                " ", _CANONICAL_SEPARATORS.sub(" ", label)
            ).strip()
            canonical_id = f"{canonical_id}_{normalized_label.replace(' ', '_')}"
        chunk_uids = _support_chunk_ids(entity.get("chunk_uid"))
        chunk_uids.extend(_support_chunk_ids(entity.get("chunk_uids")))

        entity.update({
            "canonical_id": canonical_id,
            "canonical_text": normalized_text,
            "canonicalization_confidence": 1.0,
            "canonicalization_rationale": "normalized_surface",
            "original_mention": original_mention,
        })
        canonicalized.append(entity)

        group = grouped.setdefault(canonical_id, {
            "canonical_id": canonical_id,
            "canonical_text": normalized_text,
            "aliases": set(),
            "chunk_uids": set(),
            "mention_count": 0,
        })
        group["aliases"].add(str(original_mention))
        group["chunk_uids"].update(chunk_uids)
        group["mention_count"] += 1

    canonical_groups = [
        {
            "canonical_id": group["canonical_id"],
            "canonical_text": group["canonical_text"],
            "aliases": sorted(group["aliases"]),
            "chunk_uids": sorted(group["chunk_uids"]),
            "confidence": 1.0,
            "rationale": "normalized_surface",
        }
        for group in grouped.values()
    ]
    canonical_groups.sort(key=_sort_key)
    unresolved_aliases = [
        group
        for group in canonical_groups
        if grouped[group["canonical_id"]]["mention_count"] == 1
    ]
    canonicalized.sort(key=_sort_key)
    return canonicalized, {
        "canonical_entities": canonical_groups,
        "unresolved_aliases": unresolved_aliases,
    }


def classify_entity_support(
    entities: Iterable[Mapping[str, Any]],
    relations: Iterable[Mapping[str, Any]],
    *,
    query_protected_chunk_uids: Iterable[str] = (),
) -> dict[str, list[Any]]:
    """Classify canonical entity support without changing graph topology."""
    canonical_entities, _ = canonicalize_entities(entities)
    protected_chunk_uids = {str(uid) for uid in query_protected_chunk_uids}
    elements: dict[str, dict[str, Any]] = {}

    for entity in canonical_entities:
        canonical_id = entity["canonical_id"]
        element = elements.setdefault(canonical_id, {
            "canonical_id": canonical_id,
            "canonical_text": entity["canonical_text"],
            "mention_count": 0,
            "support": "mention_only",
            "isolated_noise_candidate": False,
            "query_protected": False,
        })
        element["mention_count"] += 1
        chunk_uids = _support_chunk_ids(entity.get("chunk_uid"))
        chunk_uids.extend(_support_chunk_ids(entity.get("chunk_uids")))
        if entity.get("query_protected") or protected_chunk_uids.intersection(chunk_uids):
            element["query_protected"] = True

    active_ids: set[str] = set()
    relation_ids: set[str] = set()
    orphan_ids: dict[str, dict[str, str]] = {}
    for relation in relations:
        for endpoint in ("head", "tail"):
            if relation.get(endpoint) is None:
                continue
            endpoint_entity, _ = canonicalize_entities([{"text": relation[endpoint]}])
            canonical_id = endpoint_entity[0]["canonical_id"]
            canonical_text = endpoint_entity[0]["canonical_text"]
            relation_ids.add(canonical_id)
            if is_active_relation(relation):
                active_ids.add(canonical_id)
            if canonical_id not in elements:
                orphan_ids.setdefault(canonical_id, {
                    "canonical_id": canonical_id,
                    "canonical_text": canonical_text,
                })

    for canonical_id, element in elements.items():
        if canonical_id in active_ids:
            element["support"] = "strongly_supported"
        elif canonical_id in relation_ids:
            element["support"] = "weakly_supported"
        element["isolated_noise_candidate"] = (
            element["mention_count"] == 1 and canonical_id not in relation_ids
        )

    ordered_elements = sorted(elements.values(), key=_sort_key)
    report: dict[str, list[Any]] = {
        "elements": ordered_elements,
        "strongly_supported": [],
        "weakly_supported": [],
        "mention_only": [],
        "isolated_noise_candidates": [],
        "query_protected": [],
        "relation_orphans": sorted(orphan_ids.values(), key=_sort_key),
    }
    for element in ordered_elements:
        report[element["support"]].append(element["canonical_id"])
        if element["isolated_noise_candidate"]:
            report["isolated_noise_candidates"].append(element["canonical_id"])
        if element["query_protected"]:
            report["query_protected"].append(element["canonical_id"])
    return report
