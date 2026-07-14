# ============================================================
# GRAPH BUILDER
# Build hierarchical graph from chunks, entities, relations
# ============================================================

import networkx as nx
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from graph.relation_evidence import is_active_relation, normalize_relation_evidence


class GraphBuilder:
    def __init__(
        self,
        knn_k=None,
        sim_threshold=None,
        policy=None,
        min_degree=None,
        max_degree=None
    ):
        import config.settings as settings
        self.knn_k = knn_k if knn_k is not None else getattr(settings, "GRAPH_KNN_K", 3)
        self.sim_threshold = sim_threshold if sim_threshold is not None else getattr(settings, "GRAPH_SIM_THRESHOLD", 0.3)
        self.policy = policy if policy is not None else getattr(settings, "GRAPH_TOPOLOGY_POLICY", "adaptive")
        self.min_degree = min_degree if min_degree is not None else getattr(settings, "GRAPH_MIN_DEGREE", 1)
        self.max_degree = max_degree if max_degree is not None else getattr(settings, "GRAPH_MAX_DEGREE", 5)

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
        self._build_semantic_edges(G, chunks, active_indices, sim_matrix)

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

    def _build_semantic_edges(self, G, chunks, active_indices, sim_matrix):
        requested_policy = str(self.policy).strip().lower()
        selected_policy = requested_policy
        resolved_cutoff = float(self.sim_threshold)
        fallback_reason = ""
        degree_bounds_valid = self._valid_degree_bounds()

        if requested_policy not in {"adaptive", "fixed"}:
            selected_policy = "fixed"
            fallback_reason = f"Unsupported graph topology policy: {requested_policy}"
        elif requested_policy == "adaptive" and not degree_bounds_valid:
            selected_policy = "fixed"
            fallback_reason = "Invalid adaptive degree bounds"
        elif requested_policy == "adaptive" and len(active_indices) < 2:
            selected_policy = "fixed"
            fallback_reason = "Fewer than 2 active chunks"

        if selected_policy == "adaptive":
            try:
                semantic_edges, resolved_cutoff, unmet_nodes = self._adaptive_edges(
                    active_indices,
                    sim_matrix,
                )
            except (FloatingPointError, IndexError, TypeError, ValueError) as error:
                selected_policy = "fixed"
                fallback_reason = f"Adaptive topology unavailable: {error}"
            else:
                if unmet_nodes:
                    selected_policy = "fixed"
                    fallback_reason = (
                        "Adaptive degree bounds cannot be satisfied for: "
                        + ", ".join(str(node) for node in unmet_nodes)
                    )
                elif not semantic_edges and len(active_indices) > 1:
                    selected_policy = "fixed"
                    fallback_reason = "Adaptive topology has no semantic edges"
                else:
                    self._add_semantic_edges(G, semantic_edges)

        if selected_policy == "fixed":
            self._apply_fixed_policy(G, chunks, active_indices, sim_matrix)

        similarity_subgraph = nx.Graph()
        similarity_subgraph.add_nodes_from(f"chunk_{i}" for i in active_indices)
        for u, v, data in G.edges(data=True):
            if data.get("edge_type") == "knn_similarity":
                similarity_subgraph.add_edge(u, v)

        degrees = [int(similarity_subgraph.degree(f"chunk_{i}")) for i in active_indices]
        orphan_nodes = [
            f"chunk_{index}"
            for index, degree in zip(active_indices, degrees)
            if degree == 0
        ]
        node_count = len(active_indices)
        max_edges = node_count * (node_count - 1) / 2
        density = similarity_subgraph.number_of_edges() / max_edges if max_edges else 0.0
        degree_bounds_satisfied = (
            degree_bounds_valid
            and all(self.min_degree <= degree <= self.max_degree for degree in degrees)
        )

        G.graph["topology_metadata"] = {
            "requested_policy": requested_policy,
            "selected_policy": selected_policy,
            "resolved_cutoff": float(resolved_cutoff),
            "degree_bounds": [self.min_degree, self.max_degree],
            "degree_bounds_valid": degree_bounds_valid,
            "degree_bounds_satisfied": degree_bounds_satisfied,
            "degree_distribution": degrees,
            "edge_count": similarity_subgraph.number_of_edges(),
            "connected_components": nx.number_connected_components(similarity_subgraph),
            "density": float(density),
            "orphan_count": len(orphan_nodes),
            "orphan_nodes": orphan_nodes,
            "at_max_degree_count": sum(
                degree == self.max_degree for degree in degrees
            ) if degree_bounds_valid else 0,
            "sparse_guardrail_triggered": bool(orphan_nodes),
            "dense_guardrail_triggered": bool(
                degree_bounds_valid
                and node_count > 1
                and density > self.max_degree / (node_count - 1)
            ),
            "fallback_reason": fallback_reason,
        }

    def _valid_degree_bounds(self):
        return (
            isinstance(self.min_degree, int)
            and isinstance(self.max_degree, int)
            and 0 <= self.min_degree <= self.max_degree
        )

    def _adaptive_edges(self, active_indices, sim_matrix):
        scores = [
            float(sim_matrix[i][j])
            for offset, i in enumerate(active_indices)
            for j in active_indices[offset + 1:]
        ]
        if not scores or not np.isfinite(scores).all():
            raise ValueError("non-finite similarity scores")

        resolved_cutoff = float(np.mean(scores) + 0.5 * np.std(scores))
        if not -1.0 <= resolved_cutoff <= 1.0:
            raise ValueError("similarity cutoff is outside [-1, 1]")

        neighbors = {
            i: self._sorted_neighbors(i, active_indices, sim_matrix)
            for i in active_indices
        }
        top_neighbors = {
            i: {neighbor for neighbor, _ in candidates[:self.knn_k]}
            for i, candidates in neighbors.items()
        }
        mutual_edges = [
            (i, j, float(sim_matrix[i][j]))
            for offset, i in enumerate(active_indices)
            for j in active_indices[offset + 1:]
            if j in top_neighbors[i]
            and i in top_neighbors[j]
            and sim_matrix[i][j] >= resolved_cutoff
        ]
        mutual_edges.sort(key=lambda edge: (-edge[2], edge[0], edge[1]))

        degrees = {index: 0 for index in active_indices}
        edges = {}

        def add_edge(u, v, weight):
            edge = (min(u, v), max(u, v))
            if edge not in edges:
                edges[edge] = float(weight)
                degrees[u] += 1
                degrees[v] += 1

        def remove_edge(u, v):
            edge = (min(u, v), max(u, v))
            del edges[edge]
            degrees[u] -= 1
            degrees[v] -= 1

        for u, v, weight in mutual_edges:
            if degrees[u] < self.max_degree and degrees[v] < self.max_degree:
                add_edge(u, v, weight)

        for i in active_indices:
            for j, weight in neighbors[i]:
                if degrees[i] >= self.min_degree or weight < self.sim_threshold:
                    break
                edge = (min(i, j), max(i, j))
                if edge in edges:
                    continue
                if degrees[j] >= self.max_degree:
                    repairable = sorted(
                        (
                            (edge_weight, neighbor)
                            for (u, v), edge_weight in edges.items()
                            for neighbor in ([v] if u == j else [u] if v == j else [])
                            if degrees[neighbor] > self.min_degree
                        ),
                        key=lambda candidate: (candidate[0], candidate[1]),
                    )
                    if not repairable:
                        continue
                    _, neighbor = repairable[0]
                    remove_edge(j, neighbor)
                add_edge(i, j, weight)

        unmet_nodes = [
            index for index in active_indices if degrees[index] < self.min_degree
        ]
        return [
            (u, v, weight) for (u, v), weight in sorted(edges.items())
        ], resolved_cutoff, unmet_nodes

    @staticmethod
    def _sorted_neighbors(index, active_indices, sim_matrix):
        return sorted(
            (
                (neighbor, float(sim_matrix[index][neighbor]))
                for neighbor in active_indices
                if neighbor != index
            ),
            key=lambda candidate: (-candidate[1], candidate[0]),
        )

    @staticmethod
    def _add_semantic_edges(G, semantic_edges):
        for u, v, weight in semantic_edges:
            G.add_edge(
                f"chunk_{u}",
                f"chunk_{v}",
                weight=float(weight),
                edge_type="knn_similarity",
            )

    def _apply_fixed_policy(self, G, chunks, active_indices, sim_matrix):
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
                        edge_type="knn_similarity",
                    )
