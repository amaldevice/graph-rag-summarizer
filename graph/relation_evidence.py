"""Deterministic, backward-compatible relation evidence normalization."""

from __future__ import annotations

import json
import math
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
