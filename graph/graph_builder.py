# ============================================================
# GRAPH BUILDER
# Build hierarchical graph from chunks, entities, relations
# ============================================================

import networkx as nx
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from graph.relation_evidence import is_active_relation, normalize_relation_evidence


class GraphBuilder:
    def __init__(self, knn_k=3, sim_threshold=0.3):
        self.knn_k = knn_k
        self.sim_threshold = sim_threshold

    def build_graph(self, chunks, chunk_embeddings, all_entities, all_relations):
        G = nx.Graph()

        chunk_index_by_id = {}
        for i, chunk in enumerate(chunks):
            if chunk.get("context_only"):
                continue
            chunk_key = chunk.get("chunk_uid", chunk.get("chunk_id", i))
            chunk_index_by_id[chunk_key] = i
            G.add_node(
                f"chunk_{i}",
                type="chunk",
                chunk_uid=chunk_key,
                level=chunk.get("level", "paragraph"),
                text=chunk["text"][:120]
            )

        def entity_node_id(entity):
            canonical_id = entity.get("canonical_id")
            if canonical_id:
                return str(canonical_id)
            return f'ent_{str(entity.get("text", "")).lower().replace(" ", "_")}'

        def endpoint_key(value):
            return f'ent_{str(value).lower().replace(" ", "_")}'

        entity_nodes = {}
        endpoint_nodes = {}
        for entity in sorted(
            all_entities,
            key=lambda item: (
                entity_node_id(item),
                str(item.get("text", "")).casefold(),
                str(item.get("label", "")).casefold(),
            ),
        ):
            ent_text = entity.get("text", "")
            if not ent_text:
                continue
            node_id = entity_node_id(entity)
            entity_nodes.setdefault(node_id, entity)
            for endpoint in (ent_text, entity.get("original_mention"), entity.get("canonical_text")):
                if endpoint is None:
                    continue
                key = endpoint_key(endpoint)
                if key in endpoint_nodes and endpoint_nodes[key] != node_id:
                    endpoint_nodes[key] = None
                else:
                    endpoint_nodes[key] = node_id
            endpoint_nodes.setdefault(node_id, node_id)

        for node_id, entity in entity_nodes.items():
            G.add_node(
                node_id,
                type="entity",
                label=entity.get("label", ""),
                text=entity.get("text", ""),
            )

        for entity in all_entities:
            chunk_key = entity.get("chunk_uid", entity.get("chunk_id"))
            chunk_index = chunk_index_by_id.get(chunk_key)
            if chunk_index is None:
                continue

            if not entity.get("text"):
                continue

            node_id = entity_node_id(entity)
            if G.has_node(node_id):
                G.add_edge(
                    f"chunk_{chunk_index}",
                    node_id,
                    weight=1.0,
                    edge_type="mentions"
                )

        active_indices = [i for i, chunk in enumerate(chunks) if not chunk.get("context_only")]
        if not active_indices:
            return G

        sim_matrix = cosine_similarity(np.array(chunk_embeddings))
        active_index_set = set(active_indices)
        for i in active_indices:
            scores = sim_matrix[i].copy()
            scores[i] = -1
            for inactive_index in range(len(chunks)):
                if inactive_index not in active_index_set:
                    scores[inactive_index] = -1
            top_idx = np.argsort(scores)[-self.knn_k:][::-1]

            for j in top_idx:
                if j in active_index_set and sim_matrix[i][j] > self.sim_threshold:
                    G.add_edge(
                        f"chunk_{i}",
                        f"chunk_{j}",
                        weight=float(sim_matrix[i][j]),
                        edge_type="knn_similarity"
                    )

        relations_by_pair = {}
        for rel in normalize_relation_evidence(all_relations):
            if not is_active_relation(rel):
                continue
            if not rel.get("head") or not rel.get("tail") or not rel.get("relation"):
                continue

            h = endpoint_nodes.get(str(rel["head"]), endpoint_nodes.get(endpoint_key(rel["head"])))
            t = endpoint_nodes.get(str(rel["tail"]), endpoint_nodes.get(endpoint_key(rel["tail"])))

            if not h or not t or h == t:
                continue

            if G.has_node(h) and G.has_node(t):
                relations_by_pair.setdefault(tuple(sorted((h, t))), []).append(rel)

        for (h, t), evidence in sorted(relations_by_pair.items()):
            primary = max(
                enumerate(evidence),
                key=lambda item: (item[1]["resolved_weight"], -item[0]),
            )[1]
            support_chunk_uids = sorted({
                chunk_uid
                for relation in evidence
                for chunk_uid in relation.get("support_chunk_uids", [])
            })
            G.add_edge(
                h,
                t,
                relation=primary["relation"],
                source=primary.get("source", "unknown"),
                scope=primary.get("scope"),
                confidence=primary.get("confidence"),
                support_chunk_uids=support_chunk_uids,
                evidence_type=primary.get("evidence_type"),
                verification_state=primary.get("verification_state"),
                status=primary.get("status"),
                resolved_weight=primary.get("resolved_weight"),
                weight=primary.get("resolved_weight", 1.0),
                relation_evidence=evidence,
                evidence_count=len(evidence),
                edge_type="entity_relation",
            )

        return G
