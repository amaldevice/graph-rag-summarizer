# ============================================================
# GRAPH BUILDER
# Build hierarchical graph from chunks, entities, relations
# ============================================================

import networkx as nx
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np


class GraphBuilder:
    def __init__(self, knn_k=3, sim_threshold=0.3):
        self.knn_k = knn_k
        self.sim_threshold = sim_threshold

    def build_graph(self, chunks, chunk_embeddings, all_entities, all_relations):
        G = nx.Graph()

        for i, chunk in enumerate(chunks):
            G.add_node(
                f"chunk_{i}",
                type="chunk",
                level=chunk.get("level", "paragraph"),
                text=chunk["text"][:120]
            )

        unique_entities = list(set((e["text"], e["label"]) for e in all_entities))
        for ent_text, ent_label in unique_entities:
            node_id = f'ent_{ent_text.lower().replace(" ", "_")}'
            G.add_node(node_id, type="entity", label=ent_label, text=ent_text)

        sim_matrix = cosine_similarity(np.array(chunk_embeddings))
        for i in range(len(chunks)):
            scores = sim_matrix[i].copy()
            scores[i] = -1
            top_idx = np.argsort(scores)[-self.knn_k:][::-1]

            for j in top_idx:
                if sim_matrix[i][j] > self.sim_threshold:
                    G.add_edge(
                        f"chunk_{i}",
                        f"chunk_{j}",
                        weight=float(sim_matrix[i][j]),
                        edge_type="knn_similarity"
                    )

        for rel in all_relations:
            if not rel.get("head") or not rel.get("tail") or not rel.get("relation"):
                continue

            h = f'ent_{rel["head"].lower().replace(" ", "_")}'
            t = f'ent_{rel["tail"].lower().replace(" ", "_")}'

            if h == t:
                continue

            if G.has_node(h) and G.has_node(t):
                G.add_edge(
                    h,
                    t,
                    relation=rel["relation"],
                    source=rel.get("source", "unknown"),
                    weight=1.0,
                    edge_type="entity_relation"
                )

        return G