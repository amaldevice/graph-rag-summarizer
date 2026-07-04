# ============================================================
# COMMUNITY DETECTOR
# Leiden algorithm community detection
# ============================================================

import igraph as ig
import leidenalg


class CommunityDetector:
    def detect(self, G):
        nodes = list(G.nodes())
        idx = {n: i for i, n in enumerate(nodes)}
        edges = [(idx[u], idx[v]) for u, v in G.edges()]
        weights = [G[u][v].get('weight', 1.0) for u, v in G.edges()]
        ig_graph = ig.Graph(n=len(nodes), edges=edges)
        ig_graph.vs['name'] = nodes
        ig_graph.es['weight'] = weights
        partition = leidenalg.find_partition(ig_graph, leidenalg.ModularityVertexPartition, weights='weight', n_iterations=10, seed=42)
        community_map = {}
        communities = {}
        for cid, members in enumerate(partition):
            communities[cid] = [nodes[m] for m in members]
            for m in members:
                community_map[nodes[m]] = cid
        for n in G.nodes():
            G.nodes[n]['community'] = community_map.get(n, -1)
        return G, communities, community_map, partition.modularity
