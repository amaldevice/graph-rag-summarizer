from graph.relation_evidence import is_active_relation, normalize_relation_evidence


def test_legacy_relation_gets_complete_local_explicit_defaults():
    record = {"head": "Alpha", "relation": "supports", "tail": "Beta"}

    normalized = normalize_relation_evidence([record], support_chunk_uid="paper:chunk:2")

    assert normalized == [{
        "head": "Alpha",
        "relation": "supports",
        "tail": "Beta",
        "source": "llm",
        "scope": "local",
        "confidence": 1.0,
        "support_chunk_uids": ["paper:chunk:2"],
        "evidence_type": "explicit",
        "verification_state": "accepted",
        "status": "accepted",
        "resolved_weight": 1.0,
    }]


def test_explicit_relation_preserves_metadata_and_clamps_confidence():
    record = {
        "head": "Alpha",
        "relation": "supports",
        "tail": "Beta",
        "source": "provider-router",
        "scope": "cross_chunk",
        "confidence": 1.5,
        "support_chunk_uids": ["paper:chunk:3", "paper:chunk:1", "paper:chunk:3"],
        "evidence_type": "explicit",
        "verification_state": "verified",
        "status": "accepted",
    }

    normalized = normalize_relation_evidence([record])

    assert normalized == [{
        **record,
        "confidence": 1.0,
        "support_chunk_uids": ["paper:chunk:1", "paper:chunk:3"],
        "resolved_weight": 1.0,
    }]
    assert normalize_relation_evidence([{**record, "confidence": -0.5}])[0]["confidence"] == 0.0


def test_weak_evidence_weights_are_strictly_ordered():
    normalized = normalize_relation_evidence([
        {
            "head": "Alpha",
            "relation": "co-occurs_with",
            "tail": "Beta",
            "evidence_type": "same_sentence",
        },
        {
            "head": "Alpha",
            "relation": "co-occurs_with",
            "tail": "Gamma",
            "evidence_type": "nearby_window",
        },
        {
            "head": "Alpha",
            "relation": "co-occurs_with",
            "tail": "Delta",
            "source": "fallback",
        },
    ])
    weights = {item["evidence_type"]: item["resolved_weight"] for item in normalized}

    assert weights == {
        "same_sentence": 0.6,
        "nearby_window": 0.4,
        "same_chunk": 0.2,
    }
    assert weights["same_sentence"] > weights["nearby_window"] > weights["same_chunk"]


def test_normalization_is_stable_and_sorts_deduplicated_support_chunk_uids():
    records = [
        {
            "head": "Beta",
            "relation": "co-occurs_with",
            "tail": "Gamma",
            "source": "rule-based",
            "support_chunk_uids": ["paper:chunk:3", "paper:chunk:1", "paper:chunk:3"],
        },
        {
            "head": "Alpha",
            "relation": "supports",
            "tail": "Beta",
            "support_chunk_uids": ["paper:chunk:2"],
        },
    ]

    first = normalize_relation_evidence(records, support_chunk_uid="paper:chunk:1")
    second = normalize_relation_evidence(list(reversed(records)), support_chunk_uid="paper:chunk:1")

    assert first == second
    weak_relation = next(item for item in first if item["source"] == "rule-based")
    assert weak_relation["support_chunk_uids"] == ["paper:chunk:1", "paper:chunk:3"]


def test_only_accepted_explicit_or_verified_evidence_is_active():
    weak_relation = normalize_relation_evidence([{
        "head": "Alpha",
        "relation": "co-occurs_with",
        "tail": "Beta",
        "source": "fallback",
    }])[0]
    rejected_relation = normalize_relation_evidence([{
        "head": "Alpha",
        "relation": "supports",
        "tail": "Beta",
        "status": "rejected",
    }])[0]
    active_relation = normalize_relation_evidence([{
        "head": "Alpha",
        "relation": "supports",
        "tail": "Beta",
        "evidence_type": "verified",
    }])[0]

    assert not is_active_relation(weak_relation)
    assert not is_active_relation(rejected_relation)
    assert is_active_relation(active_relation)
