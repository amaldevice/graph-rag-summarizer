import pytest
import numpy as np
import networkx as nx
from graph.graph_builder import GraphBuilder


def test_fixed_policy_compatibility():
    # Instantiates GraphBuilder(policy="fixed", knn_k=1, sim_threshold=0.5)
    # and verifies it creates standard kNN similarity edges correctly.
    builder = GraphBuilder(policy="fixed", knn_k=1, sim_threshold=0.5)
    chunks = [
        {"chunk_id": "c0", "text": "Chunk 0", "level": "paragraph"},
        {"chunk_id": "c1", "text": "Chunk 1", "level": "paragraph"},
        {"chunk_id": "c2", "text": "Chunk 2", "level": "paragraph"},
    ]
    # Similarity matrix will have:
    # sim(0, 1) = 0.8
    # sim(0, 2) = 0.3
    # sim(1, 2) = 0.2
    v0 = [1.0, 0.0, 0.0]
    v1 = [0.8, 0.6, 0.0]
    v2 = [0.3, -1/15, np.sqrt(815)/30]
    chunk_embeddings = [v0, v1, v2]

    # For fixed policy, each node i looks at its top 1 neighbor:
    # - 0: top 1 is 1 (sim 0.8 > 0.5). Adds (0, 1).
    # - 1: top 1 is 0 (sim 0.8 > 0.5). Adds (1, 0).
    # - 2: top 1 is 0 (sim 0.3 < 0.5). No edge added.
    G = builder.build_graph(chunks, chunk_embeddings, [], [])
    
    # Assert edges
    assert G.has_edge("chunk_0", "chunk_1")
    assert not G.has_edge("chunk_0", "chunk_2")
    assert not G.has_edge("chunk_1", "chunk_2")
    
    # Check edge weight
    assert pytest.approx(G["chunk_0"]["chunk_1"]["weight"]) == 0.8
    
    # Check metadata
    metadata = G.graph["topology_metadata"]
    assert metadata["selected_policy"] == "fixed"
    assert metadata["fallback_reason"] == ""


def test_adaptive_policy_mutual_knn():
    # Verifies that with knn_k=1, mutual-kNN candidate edges are correctly generated.
    # If Chunk 0's top neighbor is Chunk 1, Chunk 1's top neighbor is Chunk 0, 
    # and Chunk 2's top neighbor is Chunk 1, the mutual-kNN edges should connect 0 and 1, 
    # but not 1 and 2.
    # Using the same similarity matrix:
    # sim(0, 1) = 0.8 (mutual kNN between 0 and 1)
    # sim(1, 2) = 0.5 (1's top is 0, 2's top is 1 - not mutual)
    # sim(0, 2) = 0.3
    v0 = [1.0, 0.0, 0.0]
    v1 = [0.8, 0.6, 0.0]
    v2 = [0.3, 13/30, np.sqrt(1.0 - 0.09 - (13/30)**2)]
    chunk_embeddings = [v0, v1, v2]
    
    chunks = [
        {"chunk_id": "c0", "text": "Chunk 0", "level": "paragraph"},
        {"chunk_id": "c1", "text": "Chunk 1", "level": "paragraph"},
        {"chunk_id": "c2", "text": "Chunk 2", "level": "paragraph"},
    ]
    
    # Use min_degree=0 to avoid min_degree reinforcement adding non-mutual edges.
    # Set sim_threshold=0.1
    builder = GraphBuilder(policy="adaptive", knn_k=1, min_degree=0, sim_threshold=0.1)
    G = builder.build_graph(chunks, chunk_embeddings, [], [])
    
    # Expected edges: (0, 1) only. (1, 2) is not mutual kNN for knn_k=1, so it shouldn't exist.
    assert G.has_edge("chunk_0", "chunk_1")
    assert not G.has_edge("chunk_1", "chunk_2")
    assert not G.has_edge("chunk_0", "chunk_2")
    
    # Check weight
    assert pytest.approx(G["chunk_0"]["chunk_1"]["weight"]) == 0.8


def test_adaptive_policy_cutoff_calculation():
    # Verifies that resolved_cutoff matches the computed mean + 0.5 * std_dev
    # of all active chunk similarities, and only edges above or equal to it are initially selected.
    # We will use knn_k=2, min_degree=0. Since knn_k=2 and there are 3 active chunks,
    # all pairs of chunks are mutual kNN candidates.
    # Similarities:
    # sim(0, 1) = 0.8
    # sim(0, 2) = 0.3
    # sim(1, 2) = 0.5
    # Scores: [0.8, 0.3, 0.5]
    # Mean: 0.5333333333333333, Std: 0.2054804554880292
    # Cutoff: Mean + 0.5 * Std = 0.6360735610773479
    v0 = [1.0, 0.0, 0.0]
    v1 = [0.8, 0.6, 0.0]
    v2 = [0.3, 13/30, np.sqrt(1.0 - 0.09 - (13/30)**2)]
    chunk_embeddings = [v0, v1, v2]
    
    chunks = [
        {"chunk_id": "c0", "text": "Chunk 0", "level": "paragraph"},
        {"chunk_id": "c1", "text": "Chunk 1", "level": "paragraph"},
        {"chunk_id": "c2", "text": "Chunk 2", "level": "paragraph"},
    ]
    
    builder = GraphBuilder(policy="adaptive", knn_k=2, min_degree=0, sim_threshold=0.1)
    G = builder.build_graph(chunks, chunk_embeddings, [], [])
    
    # Verify cutoff value in metadata
    metadata = G.graph["topology_metadata"]
    expected_mean = np.mean([0.8, 0.3, 0.5])
    expected_std = np.std([0.8, 0.3, 0.5])
    expected_cutoff = expected_mean + 0.5 * expected_std
    
    assert pytest.approx(metadata["resolved_cutoff"]) == expected_cutoff
    assert metadata["selected_policy"] == "adaptive"
    
    # Verify only (0, 1) is selected because others are below cutoff
    assert G.has_edge("chunk_0", "chunk_1")
    assert not G.has_edge("chunk_1", "chunk_2")
    assert not G.has_edge("chunk_0", "chunk_2")


def test_degree_bounds_min():
    # Instantiates GraphBuilder(policy="adaptive", knn_k=1, min_degree=1, sim_threshold=0.1)
    # and verifies that if a node has 0 mutual-kNN edges, the closest neighbor above sim_threshold
    # is added to satisfy min_degree=1.
    # Using the 4-node similarity matrix generated from search:
    # similarities:
    # sim(0, 1) = 0.1633
    # sim(0, 2) = 0.1487
    # sim(0, 3) = 0.1062
    # sim(1, 2) = 0.7702
    # sim(1, 3) = -0.4935
    # sim(2, 3) = 0.1578
    # Cutoff is 0.3247.
    # Mutual-kNN edges >= cutoff: (1, 2) only.
    # Node 0 has degree 0. Min degree is 1. Closest neighbor is 1 (0.1633 >= 0.12). Adds (0, 1).
    # Node 3 has degree 0. Min degree is 1. Closest neighbor is 2 (0.1578 >= 0.12). Adds (2, 3).
    chunk_embeddings = [
        [0.05581999934117042, 0.117486561830035, -0.0024430028398216086, 0.991501420674743],
        [-0.5221326817267621, -0.033836328294181074, -0.8293252485280231, 0.19609231936595833],
        [-0.8991108193982401, -0.22437349415230579, -0.2999579460737939, 0.2264541899592531],
        [-0.33020079544746744, -0.35559631801818936, 0.8576858474719805, 0.16998141176033632]
    ]
    
    chunks = [
        {"chunk_id": "c0", "text": "Chunk 0", "level": "paragraph"},
        {"chunk_id": "c1", "text": "Chunk 1", "level": "paragraph"},
        {"chunk_id": "c2", "text": "Chunk 2", "level": "paragraph"},
        {"chunk_id": "c3", "text": "Chunk 3", "level": "paragraph"},
    ]
    
    builder = GraphBuilder(policy="adaptive", knn_k=1, min_degree=1, sim_threshold=0.12)
    G = builder.build_graph(chunks, chunk_embeddings, [], [])
    
    # Assert final edges: (1, 2), (0, 1), (2, 3)
    assert G.has_edge("chunk_1", "chunk_2")
    assert G.has_edge("chunk_0", "chunk_1")
    assert G.has_edge("chunk_2", "chunk_3")
    assert G.number_of_edges() == 3
    
    # Degree distribution in metadata should be [1, 2, 2, 1] for active nodes 0, 1, 2, 3
    metadata = G.graph["topology_metadata"]
    assert metadata["degree_distribution"] == [1, 2, 2, 1]


def test_degree_bounds_max():
    # Instantiates GraphBuilder(policy="adaptive", knn_k=3, max_degree=1)
    # and verifies that if a node has 2+ mutual-kNN edges, the weakest edge (lowest similarity)
    # is pruned to satisfy max_degree=1.
    # similarities:
    # sim(0, 1) = 0.370056 (strongest)
    # sim(0, 2) = 0.321192 (middle)
    # sim(0, 3) = 0.302477 (weakest)
    # Others are below cutoff.
    # So initially, edges are (0, 1), (0, 2), (0, 3).
    # Enforcing max_degree=1:
    # Node 0 has degree 3. Prunes (0, 3) and (0, 2), keeping only (0, 1).
    chunk_embeddings = [
        [-0.6550841937805384, -0.019980304031565563, 0.7552394675340303, 0.008878805585365707],
        [-0.7406344397942543, -0.186029836181477, -0.14996967640414943, -0.6279829797058025],
        [-0.14880742228779348, 0.9192201849550077, 0.32252800254769215, -0.1699008246476159],
        [0.47979891746757664, -0.22980876335367964, 0.8076050994523035, 0.2544699086757195]
    ]
    
    chunks = [
        {"chunk_id": "c0", "text": "Chunk 0", "level": "paragraph"},
        {"chunk_id": "c1", "text": "Chunk 1", "level": "paragraph"},
        {"chunk_id": "c2", "text": "Chunk 2", "level": "paragraph"},
        {"chunk_id": "c3", "text": "Chunk 3", "level": "paragraph"},
    ]
    
    # We use min_degree=0 to make sure no new edges are added after pruning.
    builder = GraphBuilder(policy="adaptive", knn_k=3, min_degree=0, max_degree=1, sim_threshold=0.1)
    G = builder.build_graph(chunks, chunk_embeddings, [], [])
    
    # Assert final edges: only (0, 1) should remain
    assert G.has_edge("chunk_0", "chunk_1")
    assert not G.has_edge("chunk_0", "chunk_2")
    assert not G.has_edge("chunk_0", "chunk_3")
    assert G.number_of_edges() == 1
    
    # Let's test with max_degree=2. It should keep (0, 1) and (0, 2), pruning only (0, 3).
    builder2 = GraphBuilder(policy="adaptive", knn_k=3, min_degree=0, max_degree=2, sim_threshold=0.1)
    G2 = builder2.build_graph(chunks, chunk_embeddings, [], [])
    assert G2.has_edge("chunk_0", "chunk_1")
    assert G2.has_edge("chunk_0", "chunk_2")
    assert not G2.has_edge("chunk_0", "chunk_3")
    assert G2.number_of_edges() == 2


def test_fallback_due_to_small_input():
    # Verifies that when the input list has fewer than 2 active chunks, the builder
    # falls back to the fixed policy and records "Fewer than 2 active chunks" under fallback_reason.
    builder = GraphBuilder(policy="adaptive", knn_k=1, sim_threshold=0.5)
    
    chunks = [
        {"chunk_id": "c0", "text": "Chunk 0", "level": "paragraph"},
        {"chunk_id": "c1", "text": "Chunk 1", "level": "paragraph", "context_only": True},
    ]
    chunk_embeddings = [[1.0, 0.0], [0.8, 0.6]]
    
    G = builder.build_graph(chunks, chunk_embeddings, [], [])
    
    metadata = G.graph["topology_metadata"]
    assert metadata["selected_policy"] == "fixed"
    assert metadata["fallback_reason"] == "Fewer than 2 active chunks"
    
    # Check that only chunk_0 exists in G
    assert G.has_node("chunk_0")
    assert not G.has_node("chunk_1")


def test_determinism():
    # Runs build_graph multiple times on identical inputs but with different initial orders
    # or set orderings to verify that the resulting graph edges and properties are identical.
    import random
    
    chunk_embeddings = [
        [0.05581999934117042, 0.117486561830035, -0.0024430028398216086, 0.991501420674743],
        [-0.5221326817267621, -0.033836328294181074, -0.8293252485280231, 0.19609231936595833],
        [-0.8991108193982401, -0.22437349415230579, -0.2999579460737939, 0.2264541899592531],
        [-0.33020079544746744, -0.35559631801818936, 0.8576858474719805, 0.16998141176033632]
    ]
    chunks = [
        {"chunk_id": "c0", "text": "Chunk 0", "level": "paragraph"},
        {"chunk_id": "c1", "text": "Chunk 1", "level": "paragraph"},
        {"chunk_id": "c2", "text": "Chunk 2", "level": "paragraph"},
        {"chunk_id": "c3", "text": "Chunk 3", "level": "paragraph"},
    ]
    
    entities = [
        {"chunk_id": "c0", "text": "Alpha", "label": "ORG"},
        {"chunk_id": "c1", "text": "Beta", "label": "ORG"},
        {"chunk_id": "c2", "text": "Gamma", "label": "ORG"},
    ]
    relations = [
        {"head": "Alpha", "tail": "Beta", "relation": "collaborates", "source": "doc"},
        {"head": "Beta", "tail": "Gamma", "relation": "references", "source": "doc"},
    ]
    
    builder = GraphBuilder(policy="adaptive", knn_k=2, min_degree=1, max_degree=3, sim_threshold=0.1)
    
    # Reference build
    G_ref = builder.build_graph(chunks, chunk_embeddings, entities.copy(), relations.copy())
    
    # Run multiple times with shuffled entities and relations
    for i in range(10):
        shuffled_entities = entities.copy()
        shuffled_relations = relations.copy()
        random.seed(i)
        random.shuffle(shuffled_entities)
        random.shuffle(shuffled_relations)
        
        G = builder.build_graph(chunks, chunk_embeddings, shuffled_entities, shuffled_relations)
        
        # Verify node sets
        assert set(G.nodes()) == set(G_ref.nodes())
        # Verify edge sets
        assert set(G.edges()) == set(G_ref.edges())
        # Verify edge attributes
        for u, v in G_ref.edges():
            assert G[u][v] == G_ref[u][v]
        # Verify graph attributes (metadata)
        assert G.graph["topology_metadata"] == G_ref.graph["topology_metadata"]


def test_degenerate_inputs():
    # Test case 1: All similarities are zero (using orthogonal vectors)
    chunks = [
        {"chunk_id": "c0", "text": "Chunk 0", "level": "paragraph"},
        {"chunk_id": "c1", "text": "Chunk 1", "level": "paragraph"},
        {"chunk_id": "c2", "text": "Chunk 2", "level": "paragraph"},
    ]
    chunk_embeddings_orthogonal = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    
    builder_zeros = GraphBuilder(policy="adaptive", knn_k=1, min_degree=0, sim_threshold=0.1)
    G_zeros = builder_zeros.build_graph(chunks, chunk_embeddings_orthogonal, [], [])
    
    assert G_zeros.has_edge("chunk_0", "chunk_1")
    assert not G_zeros.has_edge("chunk_1", "chunk_2")
    assert not G_zeros.has_edge("chunk_0", "chunk_2")
    
    # Test case 2: All similarities are identical (similarity = 1.0)
    chunk_embeddings_identical = [
        [1.0, 0.0],
        [1.0, 0.0],
        [1.0, 0.0],
    ]
    builder_identical = GraphBuilder(policy="adaptive", knn_k=1, min_degree=1, sim_threshold=0.5)
    G_identical = builder_identical.build_graph(chunks, chunk_embeddings_identical, [], [])
    
    assert G_identical.has_edge("chunk_0", "chunk_1")
    assert G_identical.has_edge("chunk_0", "chunk_2")
    assert not G_identical.has_edge("chunk_1", "chunk_2")
