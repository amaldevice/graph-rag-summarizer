# ============================================================
# COMMUNITY DETECTOR
# Deterministic Leiden selection with an embedding-only diagnostic
# ============================================================

import math

import igraph as ig
import leidenalg
import networkx as nx
import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
from sklearn.metrics.pairwise import cosine_similarity


class CommunityDetector:
    """Select one bounded Leiden candidate without replacing graph communities."""

    DEFAULT_RESOLUTIONS = (0.5, 1.0, 1.5)
    DEFAULT_SEEDS = (17, 29, 43)

    def __init__(self, resolutions=None, seeds=None):
        self.resolutions = tuple(sorted(set(resolutions or self.DEFAULT_RESOLUTIONS)))
        self.seeds = tuple(sorted(set(seeds or self.DEFAULT_SEEDS)))

    def detect(self, graph, chunk_embeddings=None):
        """Annotate ``graph`` and return the selected authoritative partition.

        ``chunk_embeddings`` is optional to preserve the old detector seam.  It
        is used only for diagnostics and never changes the selected partition.
        """
        nodes, ig_graph = self._igraph(graph)
        baseline = self._baseline(nodes, ig_graph, graph, chunk_embeddings)
        candidates = self._candidates(nodes, ig_graph, graph, chunk_embeddings)
        self._add_stability(candidates)
        selected, fallback_reason = self._select(candidates, baseline)

        communities, community_map = self._normalized_communities(
            nodes, selected["membership"]
        )
        for node in graph.nodes:
            graph.nodes[node]["community"] = community_map.get(node, -1)

        graph.graph["community_selection"] = {
            "policy": "normalized_quality_coherence_stability_balance_v1",
            "baseline": baseline,
            "candidates": candidates,
            "selected": self._artifact_candidate(selected),
            "fallback_reason": fallback_reason,
            "tie_break": "score_desc_then_resolution_asc_then_seed_asc",
        }
        graph.graph["embedding_cluster_comparison"] = self._embedding_comparison(
            graph, chunk_embeddings, community_map
        )
        return graph, communities, community_map, selected["metrics"]["graph_quality"]

    @staticmethod
    def _igraph(graph):
        nodes = sorted(graph.nodes(), key=str)
        index = {node: position for position, node in enumerate(nodes)}
        edges = []
        weights = []
        for left, right, data in sorted(
            graph.edges(data=True), key=lambda edge: (str(edge[0]), str(edge[1]))
        ):
            weight = data.get("weight", 1.0)
            try:
                weight = float(weight)
            except (TypeError, ValueError):
                weight = 1.0
            if not math.isfinite(weight):
                weight = 1.0
            edges.append((index[left], index[right]))
            weights.append(weight)
        ig_graph = ig.Graph(n=len(nodes), edges=edges)
        ig_graph.vs["name"] = nodes
        if edges:
            ig_graph.es["weight"] = weights
        return nodes, ig_graph

    def _baseline(self, nodes, ig_graph, graph, chunk_embeddings):
        if not nodes:
            membership = []
        else:
            partition = leidenalg.find_partition(
                ig_graph,
                leidenalg.ModularityVertexPartition,
                weights="weight" if ig_graph.ecount() else None,
                n_iterations=10,
                seed=self.seeds[0],
            )
            membership = list(partition.membership)
        return self._candidate(
            "modularity_baseline",
            None,
            self.seeds[0],
            nodes,
            membership,
            graph,
            chunk_embeddings,
        )

    def _candidates(self, nodes, ig_graph, graph, chunk_embeddings):
        candidates = []
        if not nodes:
            return candidates
        for resolution in self.resolutions:
            for seed in self.seeds:
                partition = leidenalg.find_partition(
                    ig_graph,
                    leidenalg.RBConfigurationVertexPartition,
                    weights="weight" if ig_graph.ecount() else None,
                    resolution_parameter=resolution,
                    n_iterations=10,
                    seed=seed,
                )
                candidates.append(
                    self._candidate(
                        "rb_configuration",
                        resolution,
                        seed,
                        nodes,
                        list(partition.membership),
                        graph,
                        chunk_embeddings,
                    )
                )
        return candidates

    def _candidate(
        self, objective, resolution, seed, nodes, membership, graph, chunk_embeddings
    ):
        communities, _ = self._normalized_communities(nodes, membership)
        sizes = [len(communities[index]) for index in sorted(communities)]
        singleton_rate = (
            sum(size == 1 for size in sizes) / len(sizes) if sizes else 1.0
        )
        max_size = max(sizes, default=0)
        min_size = min(sizes, default=0)
        size_balance = min_size / max_size if max_size else 0.0
        semantic_coherence, coherence_status = self._semantic_coherence(
            communities, chunk_embeddings
        )
        rejection_reasons = []
        if not sizes:
            rejection_reasons.append("empty_communities")
        if len(sizes) > max(2, math.ceil(len(nodes) * 0.75)):
            rejection_reasons.append("fragmentation")
        if singleton_rate > 0.5:
            rejection_reasons.append("singleton_noise_rate")
        if len(sizes) > 1 and max_size / len(nodes) > 0.9:
            rejection_reasons.append("severe_size_imbalance")

        return {
            "objective": objective,
            "resolution": resolution,
            "seed": seed,
            "membership": membership,
            "metrics": {
                "community_count": len(sizes),
                "size_distribution": sizes,
                "singleton_rate": singleton_rate,
                "noise_rate": singleton_rate,
                "graph_quality": self._modularity(graph, communities),
                "semantic_coherence": semantic_coherence,
                "semantic_coherence_status": coherence_status,
                "query_coverage": {
                    "status": "not_available_at_ingest",
                    "value": None,
                },
                "size_balance": size_balance,
                "stability": {"ari": None, "nmi": None, "score": None},
            },
            "rejection_reasons": rejection_reasons,
            "accepted": not rejection_reasons,
        }

    @staticmethod
    def _normalized_communities(nodes, membership):
        groups = {}
        for node, label in zip(nodes, membership):
            groups.setdefault(label, []).append(node)
        ordered_groups = sorted(
            (sorted(members, key=str) for members in groups.values()),
            key=lambda members: tuple(str(member) for member in members),
        )
        communities = {index: members for index, members in enumerate(ordered_groups)}
        return communities, {
            member: index
            for index, members in communities.items()
            for member in members
        }

    @staticmethod
    def _modularity(graph, communities):
        if graph.number_of_edges() == 0 or not communities:
            return 0.0
        try:
            return float(nx.algorithms.community.modularity(
                graph, [set(members) for members in communities.values()], weight="weight"
            ))
        except (ArithmeticError, nx.NetworkXError, ValueError):
            return 0.0

    @staticmethod
    def _embedding_vectors(graph, chunk_embeddings):
        if chunk_embeddings is None:
            return {}
        vectors = {}
        for index, embedding in enumerate(chunk_embeddings):
            node = f"chunk_{index}"
            if not graph.has_node(node):
                continue
            vector = CommunityDetector._valid_vector(embedding)
            if vector is not None:
                vectors[node] = vector
        return vectors

    @staticmethod
    def _valid_vector(embedding):
        try:
            vector = np.asarray(embedding, dtype=float)
        except (TypeError, ValueError):
            return None
        if vector.ndim != 1 or not vector.size or not np.isfinite(vector).all():
            return None
        return vector

    def _semantic_coherence(self, communities, chunk_embeddings):
        # The detector is called before artifact relabeling, so chunk_N matches
        # the existing embedding order.  Missing embeddings remain diagnostic-only.
        if chunk_embeddings is None:
            return None, "unavailable"
        vectors = {
            f"chunk_{index}": vector
            for index, embedding in enumerate(chunk_embeddings)
            if (vector := self._valid_vector(embedding)) is not None
        }
        return self._coherence(communities, vectors)

    @staticmethod
    def _coherence(communities, vectors):
        scores = []
        for members in communities.values():
            member_vectors = [vectors[node] for node in members if node in vectors]
            if len(member_vectors) < 2:
                continue
            try:
                similarities = cosine_similarity(np.asarray(member_vectors))
            except (TypeError, ValueError):
                continue
            scores.extend(similarities[np.triu_indices(len(member_vectors), k=1)].tolist())
        return (float(np.mean(scores)), "available") if scores else (None, "unavailable")

    def _add_stability(self, candidates):
        by_resolution = {}
        for candidate in candidates:
            by_resolution.setdefault(candidate["resolution"], []).append(candidate)
        for group in by_resolution.values():
            for candidate in group:
                peers = [peer for peer in group if peer is not candidate]
                if not peers:
                    ari = nmi = 1.0
                else:
                    ari = float(np.mean([
                        adjusted_rand_score(candidate["membership"], peer["membership"])
                        for peer in peers
                    ]))
                    nmi = float(np.mean([
                        normalized_mutual_info_score(candidate["membership"], peer["membership"])
                        for peer in peers
                    ]))
                candidate["metrics"]["stability"] = {
                    "ari": ari,
                    "nmi": nmi,
                    "score": (ari + nmi) / 2,
                }

    def _select(self, candidates, baseline):
        eligible = [candidate for candidate in candidates if candidate["accepted"]]
        if not eligible:
            return baseline, "no_eligible_resolution_candidate"

        metrics = {
            "graph_quality": lambda candidate: candidate["metrics"]["graph_quality"],
            "semantic_coherence": lambda candidate: candidate["metrics"]["semantic_coherence"],
            "stability": lambda candidate: candidate["metrics"]["stability"]["score"],
            "size_balance": lambda candidate: candidate["metrics"]["size_balance"],
        }
        for name, getter in metrics.items():
            values = [getter(candidate) for candidate in eligible]
            available = [value for value in values if value is not None]
            low, high = min(available, default=0.0), max(available, default=0.0)
            for candidate, value in zip(eligible, values):
                normalized = 0.0 if value is None else (1.0 if high == low else (value - low) / (high - low))
                candidate.setdefault("normalized_metrics", {})[name] = normalized
        for candidate in eligible:
            candidate["score"] = float(np.mean(list(candidate["normalized_metrics"].values())))
        selected = min(
            eligible,
            key=lambda candidate: (
                -candidate["score"], candidate["resolution"], candidate["seed"]
            ),
        )
        return selected, ""

    def _embedding_comparison(self, graph, chunk_embeddings, community_map):
        vectors = self._embedding_vectors(graph, chunk_embeddings)
        nodes = sorted(vectors, key=str)
        active_labels = [community_map[node] for node in nodes]
        cluster_count = len(set(active_labels))
        result = {
            "algorithm": "agglomerative",
            "metric": "cosine",
            "linkage": "average",
            "active_partition_replaced": False,
            "chunk_nodes": nodes,
            "requested_cluster_count": cluster_count,
        }
        if len(nodes) < 2:
            return {**result, "status": "unavailable", "reason": "fewer_than_two_chunk_embeddings"}
        if cluster_count < 2:
            return {**result, "status": "unavailable", "reason": "single_active_community"}
        try:
            labels = AgglomerativeClustering(
                n_clusters=min(cluster_count, len(nodes)), metric="cosine", linkage="average"
            ).fit_predict(np.asarray([vectors[node] for node in nodes]))
        except Exception as exc:  # diagnostic failure must not fail the pipeline
            return {**result, "status": "unavailable", "reason": type(exc).__name__}
        sizes = sorted(
            [int(np.sum(labels == label)) for label in sorted(set(labels))], reverse=True
        )
        coherence, coherence_status = self._coherence(
            {label: [node for node, value in zip(nodes, labels) if value == label] for label in set(labels)},
            vectors,
        )
        return {
            **result,
            "status": "available",
            "cluster_count": len(sizes),
            "cluster_labels": {node: int(label) for node, label in zip(nodes, labels)},
            "size_distribution": sizes,
            "singleton_rate": sum(size == 1 for size in sizes) / len(sizes),
            "noise_rate": 0.0,
            "semantic_coherence": coherence,
            "semantic_coherence_status": coherence_status,
            "agreement": {
                "ari": float(adjusted_rand_score(active_labels, labels)),
                "nmi": float(normalized_mutual_info_score(active_labels, labels)),
            },
        }

    @staticmethod
    def _artifact_candidate(candidate):
        return {
            key: value
            for key, value in candidate.items()
            if key != "membership"
        }
