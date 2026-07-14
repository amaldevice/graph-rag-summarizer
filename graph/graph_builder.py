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
        selected_policy = self.policy
        resolved_cutoff = self.sim_threshold
        fallback_reason = ""
        
        run_adaptive = False
        if selected_policy == "adaptive":
            if len(active_indices) < 2:
                selected_policy = "fixed"
                fallback_reason = "Fewer than 2 active chunks"
            else:
                run_adaptive = True

        if run_adaptive:
            try:
                # 1. Compute unique pair similarity scores for active chunks (i < j)
                scores = []
                for idx_a, i in enumerate(active_indices):
                    for j in active_indices[idx_a + 1:]:
                        scores.append(sim_matrix[i][j])
                
                # 2. Compute mean and std of these similarity scores
                mean = float(np.mean(scores))
                std = float(np.std(scores))
                
                # 3. Derive resolved_cutoff
                resolved_cutoff = mean + 0.5 * std
                
                # 4. If resolved_cutoff is not between -1.0 and 1.0, clamp it to self.sim_threshold
                if resolved_cutoff < -1.0 or resolved_cutoff > 1.0:
                    resolved_cutoff = self.sim_threshold
                
                # 5. Generate mutual-kNN candidate edges
                top_k_for_node = {}
                for i in active_indices:
                    # Sort active chunks j != i by similarity descending, then index j ascending
                    candidates = [j for j in active_indices if j != i]
                    candidates.sort(key=lambda j: (-sim_matrix[i][j], j))
                    top_k_for_node[i] = set(candidates[:self.knn_k])
                
                semantic_edges = set()
                for idx_a, i in enumerate(active_indices):
                    for j in active_indices[idx_a + 1:]:
                        if j in top_k_for_node[i] and i in top_k_for_node[j] and sim_matrix[i][j] >= resolved_cutoff:
                            semantic_edges.add((i, j, float(sim_matrix[i][j])))
                
                # 6. Initialize degree tracking
                current_degrees = {i: 0 for i in active_indices}
                for u, v, _ in semantic_edges:
                    current_degrees[u] += 1
                    current_degrees[v] += 1
                
                # 7. Enforce min_degree per active node
                for i in sorted(active_indices):
                    candidates = [j for j in active_indices if j != i]
                    candidates.sort(key=lambda j: (-sim_matrix[i][j], j))
                    
                    for j in candidates:
                        if current_degrees[i] >= self.min_degree:
                            break
                        if sim_matrix[i][j] < self.sim_threshold:
                            break
                        
                        u, v = min(i, j), max(i, j)
                        # Check if edge already exists in semantic_edges
                        edge_exists = False
                        for ex_u, ex_v, _ in semantic_edges:
                            if ex_u == u and ex_v == v:
                                edge_exists = True
                                break
                        
                        if not edge_exists:
                            semantic_edges.add((u, v, float(sim_matrix[i][j])))
                            current_degrees[u] += 1
                            current_degrees[v] += 1
                
                # 8. Enforce max_degree per active node
                for i in sorted(active_indices):
                    # Count current degree of i dynamically from semantic_edges
                    incident_edges = []
                    for u, v, w in semantic_edges:
                        if u == i:
                            incident_edges.append((u, v, w, v))
                        elif v == i:
                            incident_edges.append((u, v, w, u))
                    
                    if len(incident_edges) > self.max_degree:
                        # Sort them by weight ascending, then neighbor index ascending
                        incident_edges.sort(key=lambda edge: (edge[2], edge[3]))
                        num_to_prune = len(incident_edges) - self.max_degree
                        for k in range(num_to_prune):
                            u, v, w, neighbor = incident_edges[k]
                            semantic_edges.discard((u, v, w))
                
                # 9. Add final set of semantic_edges to G
                for u, v, weight in semantic_edges:
                    G.add_edge(
                        f"chunk_{u}",
                        f"chunk_{v}",
                        weight=float(weight),
                        edge_type="knn_similarity"
                    )
            except Exception as e:
                selected_policy = "fixed"
                fallback_reason = str(e)
                run_adaptive = False
        
        # Fixed policy or fallback
        if not run_adaptive:
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
        
        # Collect and record metadata in G.graph["topology_metadata"]
        similarity_subgraph = nx.Graph()
        similarity_subgraph.add_nodes_from(f"chunk_{i}" for i in active_indices)
        for u, v, data in G.edges(data=True):
            if data.get("edge_type") == "knn_similarity":
                similarity_subgraph.add_edge(u, v)
        
        degrees = [int(similarity_subgraph.degree(f"chunk_{i}")) for i in active_indices]
        
        G.graph["topology_metadata"] = {
            "selected_policy": selected_policy,
            "resolved_cutoff": float(resolved_cutoff),
            "degree_bounds": [self.min_degree, self.max_degree],
            "degree_distribution": degrees,
            "edge_count": similarity_subgraph.number_of_edges(),
            "connected_components": nx.number_connected_components(similarity_subgraph),
            "fallback_reason": fallback_reason
        }
