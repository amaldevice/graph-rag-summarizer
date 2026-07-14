from copy import deepcopy
import json

import networkx as nx

from graph.relation_recovery import (
    cleanup_unsupported_entity_nodes,
    generate_relation_candidates,
    verify_relation_candidates,
)


def _graph_for(chunks, semantic_pairs=(), mention_pairs=()):
    graph = nx.Graph()
    for chunk in chunks:
        graph.add_node(
            f"chunk_{chunk['chunk_uid']}",
            type="chunk",
            chunk_uid=chunk["chunk_uid"],
        )
    for left, right in semantic_pairs:
        graph.add_edge(
            f"chunk_{left}",
            f"chunk_{right}",
            edge_type="knn_similarity",
        )
    for chunk_uid, entity_id in mention_pairs:
        graph.add_node(entity_id, type="entity")
        graph.add_edge(
            f"chunk_{chunk_uid}", entity_id, edge_type="mentions")
    return graph


def _candidate(result, head_id, tail_id):
    return next(
        candidate
        for candidate in result["generated"]
        if (candidate["head_canonical_id"], candidate["tail_canonical_id"])
        == tuple(sorted((head_id, tail_id)))
    )


def test_generate_relation_candidates_records_each_bounded_trigger_and_never_adds_distant_pairs():
    chunks = [
        {"document_id": "paper", "chunk_uid": "c1", "chunk_id": 1, "text": "one"},
        {"document_id": "paper", "chunk_uid": "c2", "chunk_id": 2, "text": "two"},
        {"document_id": "paper", "chunk_uid": "c3", "chunk_id": 3, "text": "three", "hierarchy": {"section": "methods"}},
        {"document_id": "paper", "chunk_uid": "c4", "chunk_id": 4, "text": "four", "hierarchy": {"section": "methods"}},
        {"document_id": "paper", "chunk_uid": "c5", "chunk_id": 5, "text": "five"},
        {"document_id": "paper", "chunk_uid": "c6", "chunk_id": 6, "text": "six"},
        {"document_id": "paper", "chunk_uid": "c7", "chunk_id": 7, "text": "distant"},
    ]
    entities = [
        {"canonical_id": "ent_alpha", "canonical_text": "Alpha", "text": "Alpha", "label": "ORG", "chunk_uid": "c1"},
        {"canonical_id": "ent_beta", "canonical_text": "Beta", "text": "Beta", "label": "ORG", "chunk_uid": "c2"},
        {"canonical_id": "ent_anchor", "canonical_text": "Anchor", "text": "Anchor", "label": "ORG", "chunk_uid": "c2"},
        {"canonical_id": "ent_anchor", "canonical_text": "Anchor", "text": "Anchor", "label": "ORG", "chunk_uid": "c3"},
        {"canonical_id": "ent_gamma", "canonical_text": "Gamma", "text": "Gamma", "label": "ORG", "chunk_uid": "c3"},
        {"canonical_id": "ent_delta", "canonical_text": "Delta", "text": "Delta", "label": "ORG", "chunk_uid": "c4"},
        {"canonical_id": "ent_orphan", "canonical_text": "Orphan", "text": "Orphan", "label": "ORG", "chunk_uid": "c5"},
        {"canonical_id": "ent_epsilon", "canonical_text": "Epsilon", "text": "Epsilon", "label": "ORG", "chunk_uid": "c6"},
        {"canonical_id": "ent_distant", "canonical_text": "Distant", "text": "Distant", "label": "ORG", "chunk_uid": "c7"},
    ]
    graph = _graph_for(
        chunks,
        semantic_pairs=[("c1", "c2"), ("c5", "c6")],
        mention_pairs=[("c2", "ent_anchor"), ("c3", "ent_anchor")],
    )
    before = nx.to_dict_of_dicts(graph)

    result = generate_relation_candidates(
        chunks,
        entities,
        graph,
        {"mention_only": ["ent_anchor", "ent_orphan"]},
    )

    assert _candidate(result, "ent_alpha", "ent_beta")["triggers"] == [
        "compatible_entity_label",
        "semantic_neighbor",
        "weak_orphan_recovery",
    ]
    shared = _candidate(result, "ent_beta", "ent_gamma")
    assert {"shared_graph_neighbor", "canonical_identity"}.issubset(shared["triggers"])
    assert "hierarchy_adjacency" in _candidate(result, "ent_gamma", "ent_delta")["triggers"]
    assert "weak_orphan_recovery" in _candidate(result, "ent_orphan", "ent_epsilon")["triggers"]
    assert all(
        candidate["scope"] == "cross_chunk"
        and candidate["status"] == "pending"
        and candidate["verification_state"] == "pending"
        and candidate["support_chunk_uids"] == sorted(candidate["support_chunk_uids"])
        and candidate["triggers"] == sorted(candidate["triggers"])
        for candidate in result["generated"]
    )
    assert all("ent_distant" not in (item["head_canonical_id"], item["tail_canonical_id"])
               for item in result["generated"])
    assert nx.to_dict_of_dicts(graph) == before


def test_duplicate_candidates_merge_provenance_and_are_reported_stably():
    chunks = [
        {"document_id": "paper", "chunk_uid": "c1", "chunk_id": 1, "text": "one"},
        {"document_id": "paper", "chunk_uid": "c2", "chunk_id": 2, "text": "two"},
        {"document_id": "paper", "chunk_uid": "c3", "chunk_id": 3, "text": "three"},
    ]
    entities = [
        {"canonical_id": "ent_alpha", "canonical_text": "Alpha", "label": "ORG", "chunk_uid": "c1"},
        {"canonical_id": "ent_alpha", "canonical_text": "Alpha", "label": "ORG", "chunk_uid": "c2"},
        {"canonical_id": "ent_beta", "canonical_text": "Beta", "label": "ORG", "chunk_uid": "c2"},
        {"canonical_id": "ent_beta", "canonical_text": "Beta", "label": "ORG", "chunk_uid": "c3"},
    ]
    graph = _graph_for(
        chunks,
        semantic_pairs=[("c1", "c2"), ("c2", "c3")],
        mention_pairs=[
            ("c1", "ent_alpha"),
            ("c2", "ent_alpha"),
            ("c2", "ent_beta"),
            ("c3", "ent_beta"),
        ],
    )

    result = generate_relation_candidates(
        chunks, entities, graph, {"mention_only": ["ent_alpha"]}
    )
    candidate = _candidate(result, "ent_alpha", "ent_beta")

    assert candidate["support_chunk_uids"] == ["c1", "c2", "c3"]
    assert {"semantic_neighbor", "shared_graph_neighbor", "canonical_identity"}.issubset(
        candidate["triggers"]
    )
    assert result["deduplicated"]
    assert all(item["duplicate_of"] == {
        "head_canonical_id": "ent_alpha",
        "tail_canonical_id": "ent_beta",
    } for item in result["deduplicated"])


def test_generation_is_input_order_stable():
    chunks = [
        {"document_id": "paper", "chunk_uid": "c1", "chunk_id": 1, "text": "one"},
        {"document_id": "paper", "chunk_uid": "c2", "chunk_id": 2, "text": "two"},
    ]
    entities = [
        {"canonical_id": "ent_alpha", "canonical_text": "Alpha", "label": "ORG", "chunk_uid": "c1"},
        {"canonical_id": "ent_beta", "canonical_text": "Beta", "label": "ORG", "chunk_uid": "c2"},
    ]
    graph = _graph_for(chunks, semantic_pairs=[("c1", "c2")])

    first = generate_relation_candidates(
        chunks, entities, graph, {"mention_only": ["ent_alpha"]}
    )
    second = generate_relation_candidates(
        list(reversed(deepcopy(chunks))),
        list(reversed(deepcopy(entities))),
        graph,
        {"mention_only": ["ent_alpha"]},
    )

    assert first == second


def test_generation_reports_each_budget_level_in_sorted_candidate_order():
    chunks = [
        {"document_id": "paper", "chunk_uid": "c1", "chunk_id": 1, "text": "one"},
        {"document_id": "paper", "chunk_uid": "c2", "chunk_id": 2, "text": "two"},
        {"document_id": "paper", "chunk_uid": "c3", "chunk_id": 3, "text": "three"},
    ]
    entities = [
        {"canonical_id": "ent_alpha", "canonical_text": "Alpha", "label": "ORG", "chunk_uid": "c1"},
        {"canonical_id": "ent_beta", "canonical_text": "Beta", "label": "ORG", "chunk_uid": "c2"},
        {"canonical_id": "ent_gamma", "canonical_text": "Gamma", "label": "ORG", "chunk_uid": "c3"},
    ]
    graph = _graph_for(chunks, semantic_pairs=[("c1", "c2"), ("c1", "c3")])

    per_entity = generate_relation_candidates(
        chunks,
        entities,
        graph,
        {"mention_only": ["ent_alpha"]},
        per_entity_cap=1,
        per_chunk_cap=9,
        total_cap=9,
    )
    per_chunk = generate_relation_candidates(
        chunks,
        entities,
        graph,
        {"mention_only": ["ent_alpha"]},
        per_entity_cap=9,
        per_chunk_cap=1,
        total_cap=9,
    )
    total = generate_relation_candidates(
        chunks,
        entities,
        graph,
        {"mention_only": ["ent_alpha"]},
        per_entity_cap=9,
        per_chunk_cap=9,
        total_cap=1,
    )

    assert len(per_entity["generated"]) == 1
    assert {item["reason"] for item in per_entity["budget_rejected"]} == {"per_entity_cap"}
    assert len(per_chunk["generated"]) == 1
    assert {item["reason"] for item in per_chunk["budget_rejected"]} == {"per_chunk_cap"}
    assert len(total["generated"]) == 1
    assert {item["reason"] for item in total["budget_rejected"]} == {"total_cap"}


def test_document_id_mismatch_never_resolves_a_unique_foreign_chunk_uid():
    chunks = [
        {"document_id": "paper", "chunk_uid": "paper-1", "chunk_id": 1, "text": "one"},
        {"document_id": "paper", "chunk_uid": "paper-2", "chunk_id": 2, "text": "two"},
        {"document_id": "other", "chunk_uid": "other-1", "chunk_id": 1, "text": "foreign one"},
        {"document_id": "other", "chunk_uid": "other-2", "chunk_id": 2, "text": "foreign two"},
    ]
    entities = [
        {"document_id": "paper", "canonical_id": "ent_paper_a", "canonical_text": "A", "label": "ORG", "chunk_uid": "paper-1"},
        {"document_id": "paper", "canonical_id": "ent_paper_b", "canonical_text": "B", "label": "ORG", "chunk_uid": "paper-2"},
        # This record claims to be paper-local, so it must not silently attach
        # to the unique same-UID chunk in another document.
        {"document_id": "paper", "canonical_id": "ent_mismatched", "canonical_text": "Wrong", "label": "ORG", "chunk_uid": "other-1"},
        {"document_id": "other", "canonical_id": "ent_other", "canonical_text": "Other", "label": "ORG", "chunk_uid": "other-2"},
    ]
    graph = _graph_for(
        chunks,
        semantic_pairs=[("paper-1", "paper-2"), ("other-1", "other-2")],
    )

    result = generate_relation_candidates(
        chunks, entities, graph, {"mention_only": ["ent_paper_a"]}
    )

    assert [(item["head_canonical_id"], item["tail_canonical_id"])
            for item in result["generated"]] == [("ent_paper_a", "ent_paper_b")]
    assert all(
        "ent_mismatched" not in (item["head_canonical_id"], item["tail_canonical_id"])
        for item in result["generated"]
    )


def test_semantic_chain_does_not_create_a_transitive_all_pairs_candidate():
    chunks = [
        {"document_id": "paper", "chunk_uid": "c1", "chunk_id": 1, "text": "one"},
        {"document_id": "paper", "chunk_uid": "c2", "chunk_id": 2, "text": "two"},
        {"document_id": "paper", "chunk_uid": "c3", "chunk_id": 3, "text": "three"},
    ]
    entities = [
        {"canonical_id": "ent_alpha", "canonical_text": "Alpha", "label": "ORG", "chunk_uid": "c1"},
        {"canonical_id": "ent_beta", "canonical_text": "Beta", "label": "ORG", "chunk_uid": "c2"},
        {"canonical_id": "ent_gamma", "canonical_text": "Gamma", "label": "ORG", "chunk_uid": "c3"},
    ]
    graph = _graph_for(chunks, semantic_pairs=[("c1", "c2"), ("c2", "c3")])

    result = generate_relation_candidates(
        chunks, entities, graph, {"mention_only": ["ent_beta"]}
    )

    generated_pairs = {
        (item["head_canonical_id"], item["tail_canonical_id"])
        for item in result["generated"]
    }
    assert generated_pairs == {("ent_alpha", "ent_beta"), ("ent_beta", "ent_gamma")}
    assert ("ent_alpha", "ent_gamma") not in generated_pairs


def test_incompatible_entity_labels_do_not_form_relation_candidates():
    chunks = [
        {"document_id": "paper", "chunk_uid": "c1", "chunk_id": 1, "text": "one"},
        {"document_id": "paper", "chunk_uid": "c2", "chunk_id": 2, "text": "two"},
    ]
    entities = [
        {"canonical_id": "ent_company", "canonical_text": "Company", "label": "ORG", "chunk_uid": "c1"},
        {"canonical_id": "ent_person", "canonical_text": "Person", "label": "PERSON", "chunk_uid": "c2"},
    ]

    result = generate_relation_candidates(
        chunks,
        entities,
        _graph_for(chunks, semantic_pairs=[("c1", "c2")]),
        {"mention_only": ["ent_company"]},
    )

    assert result == {"generated": [], "deduplicated": [], "budget_rejected": []}


def test_shuffled_inputs_under_caps_keep_the_full_result_byte_for_byte_stable():
    chunks = [
        {"document_id": "paper", "chunk_uid": "c1", "chunk_id": 1, "text": "one"},
        {"document_id": "paper", "chunk_uid": "c2", "chunk_id": 2, "text": "two"},
        {"document_id": "paper", "chunk_uid": "c3", "chunk_id": 3, "text": "three"},
    ]
    entities = [
        {"canonical_id": "ent_alpha", "canonical_text": "Alpha", "label": "ORG", "chunk_uid": "c1"},
        {"canonical_id": "ent_beta", "canonical_text": "Beta", "label": "ORG", "chunk_uid": "c2"},
        {"canonical_id": "ent_gamma", "canonical_text": "Gamma", "label": "ORG", "chunk_uid": "c3"},
    ]
    graph = _graph_for(chunks, semantic_pairs=[("c1", "c2"), ("c1", "c3")])

    first = generate_relation_candidates(
        chunks,
        entities,
        graph,
        {"mention_only": ["ent_alpha"]},
        per_entity_cap=9,
        per_chunk_cap=9,
        total_cap=1,
    )
    second = generate_relation_candidates(
        [deepcopy(chunks[index]) for index in (2, 0, 1)],
        [deepcopy(entities[index]) for index in (1, 2, 0)],
        graph,
        {"mention_only": ["ent_alpha"]},
        per_entity_cap=9,
        per_chunk_cap=9,
        total_cap=1,
    )

    assert json.dumps(first, ensure_ascii=False, separators=(",", ":")) == json.dumps(
        second, ensure_ascii=False, separators=(",", ":")
    )
    assert first["generated"][0]["head_canonical_id"] == "ent_alpha"
    assert first["generated"][0]["tail_canonical_id"] == "ent_beta"
    assert first["budget_rejected"] == [
        {
            "candidate": {
                "document_id": "paper",
                "head": "Alpha",
                "tail": "Gamma",
                "head_canonical_id": "ent_alpha",
                "head_text": "Alpha",
                "tail_canonical_id": "ent_gamma",
                "tail_text": "Gamma",
                "support_chunk_uids": ["c1", "c3"],
                "triggers": [
                    "compatible_entity_label",
                    "semantic_neighbor",
                    "weak_orphan_recovery",
                ],
                "scope": "cross_chunk",
                "status": "pending",
                "verification_state": "pending",
            },
            "reason": "total_cap",
            "limit": 1,
        }
    ]


def test_all_strong_semantic_neighbors_do_not_request_recovery_candidates():
    chunks = [
        {"document_id": "paper", "chunk_uid": "c1", "chunk_id": 1, "text": "one"},
        {"document_id": "paper", "chunk_uid": "c2", "chunk_id": 2, "text": "two"},
    ]
    entities = [
        {"canonical_id": "ent_alpha", "canonical_text": "Alpha", "label": "ORG", "chunk_uid": "c1"},
        {"canonical_id": "ent_beta", "canonical_text": "Beta", "label": "ORG", "chunk_uid": "c2"},
    ]

    result = generate_relation_candidates(
        chunks,
        entities,
        _graph_for(chunks, semantic_pairs=[("c1", "c2")]),
        {"strongly_supported": ["ent_alpha", "ent_beta"]},
    )

    assert result == {"generated": [], "deduplicated": [], "budget_rejected": []}


def _pending_candidate():
    return {
        "document_id": "paper",
        "head": "Alpha",
        "head_text": "Alpha",
        "head_canonical_id": "ent_alpha",
        "tail": "Beta",
        "tail_text": "Beta",
        "tail_canonical_id": "ent_beta",
        "support_chunk_uids": ["c1", "c2"],
        "triggers": ["semantic_neighbor", "weak_orphan_recovery"],
        "scope": "cross_chunk",
        "status": "pending",
        "verification_state": "pending",
    }


class _Provider:
    def __init__(self, responses, chain=("fake",)):
        self.responses = iter(responses)
        self.chain = list(chain)
        self.calls = []
        self.active_provider = "fake"

    def resolve_chain(self):
        return self.chain

    def call_llm(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def _verification_inputs():
    chunks = [
        {"chunk_uid": "c1", "text": "A" * 700, "hierarchy": {"section": "one"}},
        {"chunk_uid": "c2", "text": "B" * 700, "hierarchy": {"section": "two"}},
        {"chunk_uid": "c3", "text": "C" * 700, "hierarchy": {"section": "three"}},
    ]
    graph = _graph_for(chunks, semantic_pairs=[("c1", "c3")])
    return chunks, graph


def test_verification_accepts_only_bounded_strict_responses_and_never_exceeds_candidates():
    chunks, graph = _verification_inputs()
    candidate = _pending_candidate()
    second = {**candidate, "head": "Gamma", "head_text": "Gamma", "head_canonical_id": "ent_gamma"}
    provider = _Provider([
        json.dumps({
            "status": "accepted",
            "relation": "supports",
            "confidence": 0.8,
            "support_chunk_uids": ["c1"],
        }),
        json.dumps({
            "status": "rejected",
            "relation": None,
            "confidence": None,
            "support_chunk_uids": [],
        }),
    ])

    evidence, decisions = verify_relation_candidates(
        [candidate, second], chunks, graph, [], provider
    )

    assert len(provider.calls) == 2
    assert [item["status"] for item in decisions] == ["accepted", "rejected"]
    assert evidence[0]["evidence_type"] == "verified"
    assert evidence[0]["support_chunk_uids"] == ["c1"]
    assert all(
        len(chunk["text"]) <= 600
        for decision in decisions
        for chunk in decision["evidence_window"]["chunks"]
    )
    assert all(
        len(decision["evidence_window"]["chunks"]) <= 8
        for decision in decisions
    )


def test_verification_uses_router_validator_to_fall_through_malformed_provider_result():
    class FallbackProvider:
        active_provider = "provider-b"

        def __init__(self):
            self.calls = []

        def resolve_chain(self):
            return ["provider-a", "provider-b"]

        def call_llm(self, system_prompt, user_prompt, response_validator=None):
            del system_prompt, user_prompt
            assert response_validator is not None
            malformed = "not-json"
            accepted = json.dumps({
                "status": "accepted",
                "relation": "supports",
                "confidence": 0.9,
                "support_chunk_uids": ["c1"],
            })
            self.calls.extend([malformed, accepted])
            assert response_validator(malformed) is False
            assert response_validator(accepted) is True
            return accepted

    chunks, graph = _verification_inputs()
    evidence, decisions = verify_relation_candidates(
        [_pending_candidate()], chunks, graph, [], FallbackProvider()
    )

    assert decisions[0]["status"] == "accepted"
    assert evidence[0]["relation"] == "supports"


def test_verification_preserves_rejected_insufficient_and_unavailable_without_throwing():
    chunks, graph = _verification_inputs()
    candidate = _pending_candidate()
    responses = [
        json.dumps({
            "status": "rejected",
            "relation": None,
            "confidence": None,
            "support_chunk_uids": [],
        }),
        json.dumps({
            "status": "insufficient",
            "relation": None,
            "confidence": None,
            "support_chunk_uids": [],
        }),
        "not json",
    ]
    provider = _Provider(responses)

    evidence, decisions = verify_relation_candidates(
        [candidate, candidate, candidate], chunks, graph, [], provider
    )
    unavailable = _Provider([], chain=())
    unavailable_evidence, unavailable_decisions = verify_relation_candidates(
        [candidate], chunks, graph, [], unavailable
    )
    failing = _Provider([RuntimeError("provider down")])
    failing_evidence, failing_decisions = verify_relation_candidates(
        [candidate], chunks, graph, [], failing
    )

    assert [item["status"] for item in decisions] == ["rejected", "insufficient", "insufficient"]
    assert decisions[-1]["reason"] == "malformed_response"
    assert [item["status"] for item in evidence] == ["rejected", "insufficient", "insufficient"]
    assert unavailable.calls == []
    assert unavailable_decisions[0]["status"] == "unavailable"
    assert unavailable_evidence[0]["status"] == "unavailable"
    assert failing_decisions[0]["status"] == "unavailable"
    assert failing_decisions[0]["reason"] == "provider_call_failed"
    assert failing_evidence[0]["status"] == "unavailable"


def test_cleanup_removes_only_unprotected_isolated_entity_nodes():
    graph = nx.Graph()
    graph.add_node("chunk_c1", type="chunk")
    graph.add_node("ent_remove", type="entity")
    graph.add_node("ent_keep", type="entity")
    graph.add_edge("chunk_c1", "ent_remove", edge_type="mentions")
    graph.add_edge("chunk_c1", "ent_keep", edge_type="mentions")

    cleanup = cleanup_unsupported_entity_nodes(graph, {
        "elements": [
            {"canonical_id": "ent_remove", "isolated_noise_candidate": True, "query_protected": False},
            {"canonical_id": "ent_keep", "isolated_noise_candidate": True, "query_protected": True},
        ]
    })

    assert cleanup == {
        "removed_entity_ids": ["ent_remove"],
        "removed": [{"canonical_id": "ent_remove", "reason": "isolated_noise_candidate"}],
        "preserved": [{"canonical_id": "ent_keep", "reason": "query_protected"}],
    }
    assert not graph.has_node("ent_remove")
    assert graph.has_node("ent_keep")
    assert graph.has_node("chunk_c1")


def test_generation_caps_each_neighborhood_before_document_budget():
    chunks = [
        {"document_id": "paper", "chunk_uid": "c1", "chunk_id": 1, "text": "one"},
        {"document_id": "paper", "chunk_uid": "c2", "chunk_id": 2, "text": "two"},
    ]
    entities = [
        {"canonical_id": f"ent_left_{index}", "canonical_text": f"Left {index}", "label": "ORG", "chunk_uid": "c1"}
        for index in range(3)
    ] + [
        {"canonical_id": f"ent_right_{index}", "canonical_text": f"Right {index}", "label": "ORG", "chunk_uid": "c2"}
        for index in range(3)
    ]

    result = generate_relation_candidates(
        chunks,
        entities,
        _graph_for(chunks, semantic_pairs=[("c1", "c2")]),
        {"mention_only": ["ent_left_0"]},
        per_neighborhood_cap=2,
        per_entity_cap=9,
        per_chunk_cap=9,
        total_cap=9,
    )

    assert len(result["generated"]) == 2
    assert {item["reason"] for item in result["budget_rejected"]} == {"per_neighborhood_cap"}
