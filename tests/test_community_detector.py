import networkx as nx
import pytest

from graph.community_detector import CommunityDetector


def _two_community_graph(order=range(6)):
    graph = nx.Graph()
    for index in order:
        graph.add_node(f"chunk_{index}", type="chunk")
    graph.add_weighted_edges_from([
        ("chunk_0", "chunk_1", 1.0),
        ("chunk_0", "chunk_2", 1.0),
        ("chunk_1", "chunk_2", 1.0),
        ("chunk_3", "chunk_4", 1.0),
        ("chunk_3", "chunk_5", 1.0),
        ("chunk_4", "chunk_5", 1.0),
        ("chunk_2", "chunk_3", 0.1),
    ])
    return graph


EMBEDDINGS = [
    [1.0, 0.0], [0.95, 0.05], [0.9, 0.1],
    [0.0, 1.0], [0.05, 0.95], [0.1, 0.9],
]


def test_selects_bounded_deterministic_leiden_candidate_and_records_metrics():
    detector = CommunityDetector(resolutions=(0.5, 1.0), seeds=(17, 29))
    graph, communities, community_map, modularity = detector.detect(
        _two_community_graph(), EMBEDDINGS
    )

    selection = graph.graph["community_selection"]
    assert selection["baseline"]["objective"] == "modularity_baseline"
    assert len(selection["candidates"]) == 4
    assert selection["selected"]["objective"] == "rb_configuration"
    assert selection["fallback_reason"] == ""
    assert modularity == selection["selected"]["metrics"]["graph_quality"]
    assert set(community_map) == set(graph.nodes)
    assert set(member for members in communities.values() for member in members) == set(graph.nodes)
    for candidate in selection["candidates"]:
        metrics = candidate["metrics"]
        assert candidate["resolution"] in {0.5, 1.0}
        assert candidate["seed"] in {17, 29}
        assert metrics["community_count"] > 0
        assert metrics["size_distribution"]
        assert metrics["stability"]["ari"] is not None
        assert metrics["stability"]["nmi"] is not None
        assert metrics["query_coverage"]["status"] == "not_available_at_ingest"

    repeat, _, repeat_map, _ = detector.detect(_two_community_graph(), EMBEDDINGS)
    assert repeat_map == community_map
    assert repeat.graph["community_selection"]["selected"] == selection["selected"]


def test_selection_is_insertion_order_independent():
    detector = CommunityDetector(resolutions=(0.5, 1.0), seeds=(17, 29))
    first, _, first_map, _ = detector.detect(_two_community_graph(), EMBEDDINGS)
    second, _, second_map, _ = detector.detect(
        _two_community_graph(order=reversed(range(6))), EMBEDDINGS
    )

    assert first_map == second_map
    assert first.graph["community_selection"]["selected"] == second.graph["community_selection"]["selected"]


def test_rejected_singleton_candidates_fall_back_to_modularity_baseline():
    graph = nx.Graph()
    graph.add_nodes_from((f"chunk_{index}", {"type": "chunk"}) for index in range(3))

    graph, communities, _, _ = CommunityDetector().detect(
        graph, [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]]
    )

    selection = graph.graph["community_selection"]
    assert selection["fallback_reason"] == "no_eligible_resolution_candidate"
    assert selection["selected"]["objective"] == "modularity_baseline"
    assert all("singleton_noise_rate" in candidate["rejection_reasons"] for candidate in selection["candidates"])
    assert len(communities) == 3


def test_embedding_clustering_is_diagnostic_only_and_can_disagree():
    graph = nx.Graph()
    graph.add_nodes_from((f"chunk_{index}", {"type": "chunk"}) for index in range(4))
    graph.add_weighted_edges_from([
        ("chunk_0", "chunk_1", 1.0),
        ("chunk_2", "chunk_3", 1.0),
    ])
    # The embeddings deliberately group (0, 2) and (1, 3), unlike graph edges.
    embeddings = [[1.0, 0.0], [0.0, 1.0], [0.95, 0.05], [0.05, 0.95]]

    graph, _, community_map, _ = CommunityDetector(
        resolutions=(1.0,), seeds=(17,)
    ).detect(graph, embeddings)

    comparison = graph.graph["embedding_cluster_comparison"]
    assert comparison["status"] == "available"
    assert comparison["active_partition_replaced"] is False
    assert comparison["agreement"]["ari"] < 1.0
    assert set(community_map) == set(graph.nodes)


def test_embedding_diagnostic_degrades_for_small_or_failing_input(monkeypatch):
    graph = nx.Graph()
    graph.add_node("chunk_0", type="chunk")
    graph, _, _, _ = CommunityDetector().detect(graph, [[1.0, 0.0]])
    assert graph.graph["embedding_cluster_comparison"]["status"] == "unavailable"
    assert graph.graph["embedding_cluster_comparison"]["reason"] == "fewer_than_two_chunk_embeddings"

    class BrokenClustering:
        def __init__(self, **kwargs):
            del kwargs

        def fit_predict(self, vectors):
            del vectors
            raise RuntimeError("diagnostic unavailable")

    monkeypatch.setattr("graph.community_detector.AgglomerativeClustering", BrokenClustering)
    graph, _, _, _ = CommunityDetector(resolutions=(1.0,), seeds=(17,)).detect(
        _two_community_graph(), EMBEDDINGS
    )
    comparison = graph.graph["embedding_cluster_comparison"]
    assert comparison["status"] == "unavailable"
    assert comparison["reason"] == "RuntimeError"


@pytest.mark.parametrize("embeddings", [None, [[1.0, 0.0], "not-a-vector"]])
def test_embedding_diagnostic_does_not_break_legacy_detect_seam(embeddings):
    graph, communities, community_map, _ = CommunityDetector(
        resolutions=(1.0,), seeds=(17,)
    ).detect(_two_community_graph(), embeddings)

    assert communities
    assert community_map
    assert graph.graph["embedding_cluster_comparison"]["status"] == "unavailable"
