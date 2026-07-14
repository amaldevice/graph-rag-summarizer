from graph.relation_evidence import (
    canonicalize_entities,
    classify_entity_support,
    is_active_relation,
    normalize_relation_evidence,
)


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


def test_canonicalize_entities_merges_only_safe_surface_variants():
    canonical_entities, report = canonicalize_entities([
        {"text": "Acme, Inc.", "label": "ORG", "chunk_uid": "paper:chunk:2"},
        {"text": "  acme inc  ", "label": "ORG", "chunk_uid": "paper:chunk:1"},
        {"text": "C++", "label": "PRODUCT"},
        {"text": "C", "label": "PRODUCT"},
    ])

    assert {entity["canonical_id"] for entity in canonical_entities} == {
        "ent_acme_inc", "ent_c", "ent_c++",
    }
    assert {entity["original_mention"] for entity in canonical_entities} == {
        "Acme, Inc.",
        "  acme inc  ",
        "C++",
        "C",
    }
    assert all(entity["canonicalization_confidence"] == 1.0 for entity in canonical_entities)
    assert all(
        entity["canonicalization_rationale"] == "normalized_surface"
        for entity in canonical_entities
    )
    assert report["canonical_entities"][0] == {
        "canonical_id": "ent_acme_inc",
        "canonical_text": "acme inc",
        "aliases": ["  acme inc  ", "Acme, Inc."],
        "chunk_uids": ["paper:chunk:1", "paper:chunk:2"],
        "confidence": 1.0,
        "rationale": "normalized_surface",
    }
    assert {item["canonical_id"] for item in report["unresolved_aliases"]} == {
        "ent_c", "ent_c++",
    }


def test_entity_support_classifies_orphans_and_query_protection():
    entities = [
        {"text": "Alpha", "chunk_uid": "paper:strong:1"},
        {"text": "Beta", "chunk_uid": "paper:strong:2"},
        {"text": "Weak Head", "chunk_uid": "paper:weak:1"},
        {"text": "Weak Tail", "chunk_uid": "paper:weak:2"},
        {"text": "Mention Only", "chunk_uid": "paper:mention:1"},
        {"text": "Flag Protected", "query_protected": True},
        {"text": "Chunk Protected", "chunk_uid": "paper:protected:1"},
    ]
    relations = normalize_relation_evidence([
        {
            "head": "Alpha",
            "relation": "supports",
            "tail": "Beta",
            "evidence_type": "verified",
        },
        {
            "head": "Weak Head",
            "relation": "co-occurs_with",
            "tail": "Weak Tail",
            "source": "fallback",
        },
        {
            "head": "Relation Orphan",
            "relation": "references",
            "tail": "Missing Endpoint",
            "source": "fallback",
        },
    ])

    canonical_entities, _ = canonicalize_entities(entities)
    report = classify_entity_support(
        canonical_entities,
        relations,
        query_protected_chunk_uids={"paper:protected:1"},
    )

    assert report["strongly_supported"] == ["ent_alpha", "ent_beta"]
    assert report["weakly_supported"] == ["ent_weak_head", "ent_weak_tail"]
    assert report["mention_only"] == [
        "ent_chunk_protected",
        "ent_flag_protected",
        "ent_mention_only",
    ]
    assert report["isolated_noise_candidates"] == report["mention_only"]
    assert report["query_protected"] == ["ent_chunk_protected", "ent_flag_protected"]
    assert {
        orphan["canonical_id"] for orphan in report["relation_orphans"]
    } == {"ent_missing_endpoint", "ent_relation_orphan"}

    by_id = {entity["canonical_id"]: entity for entity in report["elements"]}
    assert by_id["ent_chunk_protected"]["support"] == "mention_only"
    assert by_id["ent_chunk_protected"]["query_protected"] is True
    assert by_id["ent_flag_protected"]["query_protected"] is True


def test_entity_helpers_are_permutation_stable():
    entities = [
        {"text": "Acme, Inc.", "chunk_uid": "paper:2"},
        {"text": "acme inc", "chunk_uid": "paper:1"},
        {"text": "Beta"},
    ]
    relations = normalize_relation_evidence([{
        "head": "Acme Inc",
        "relation": "supports",
        "tail": "Beta",
    }])

    first_entities, first_aliases = canonicalize_entities(entities)
    second_entities, second_aliases = canonicalize_entities(list(reversed(entities)))

    assert (first_entities, first_aliases) == (second_entities, second_aliases)
    assert classify_entity_support(first_entities, relations) == classify_entity_support(
        second_entities, list(reversed(relations))
    )


def test_canonicalization_separates_conflicting_entity_labels():
    canonical_entities, report = canonicalize_entities([
        {"text": "Washington", "label": "PERSON"},
        {"text": "Washington", "type": "GPE"},
    ])

    assert {entity["canonical_id"] for entity in canonical_entities} == {
        "ent_washington_gpe",
        "ent_washington_person",
    }
    assert [group["canonical_id"] for group in report["canonical_entities"]] == [
        "ent_washington_gpe",
        "ent_washington_person",
    ]
