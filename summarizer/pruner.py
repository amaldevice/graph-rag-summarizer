# ============================================================
# PRUNER / RE-RANKER
# Select top-k chunk nodes per community for summarization stage
# ============================================================

import json
import math
import re
from pathlib import Path

import networkx as nx
import pandas as pd


class SummaryPruner:
    def __init__(
        self,
        top_k_per_community=3,
        top_k_global=10,
        min_score=0.0,
        min_sentence_words=8,
        max_parent_depth=2,
        context_char_budget=12_000,
        min_community_chars=600,
        max_community_chars=4_800,
        max_community_share=0.8,
        relevance_floor=0.05,
        min_marginal_gain=0.01,
    ):
        # Kept only so older callers can continue constructing this class.
        # Allocation below deliberately does not use fixed top-k limits.
        self.top_k_per_community = top_k_per_community
        self.top_k_global = top_k_global
        self.min_score = min_score
        self.min_sentence_words = min_sentence_words
        self.max_parent_depth = max_parent_depth
        self.context_char_budget = max(0, int(context_char_budget))
        self.min_community_chars = max(0, int(min_community_chars))
        self.max_community_chars = max(0, int(max_community_chars))
        self.max_community_share = min(1.0, max(0.0, float(max_community_share)))
        self.relevance_floor = max(0.0, float(relevance_floor))
        self.min_marginal_gain = max(0.0, float(min_marginal_gain))

    def _normalize_chunk_id(self, node_name: str):
        if not isinstance(node_name, str):
            return None
        if not node_name.startswith("chunk_"):
            return None
        try:
            return int(node_name.split("_")[1])
        except (IndexError, ValueError):
            return None

    def _chunk_lookup(self, chunks):
        lookup = {}
        for idx, chunk in enumerate(chunks):
            chunk_id = chunk.get("chunk_id", idx)
            lookup[idx] = chunk
            if chunk_id not in lookup:
                lookup[chunk_id] = chunk
        return lookup

    def _parent_context(self, chunk, chunks):
        if not chunk or self.max_parent_depth <= 0:
            return []
        if "parent_context" in chunk:
            return list(chunk.get("parent_context") or [])[:self.max_parent_depth]

        by_uid = {}
        by_document_local_id = {}
        by_hierarchy_id = {}
        for candidate in chunks:
            candidate_id = candidate.get("chunk_id")
            candidate_uid = candidate.get("chunk_uid")
            if candidate_uid is not None:
                by_uid[candidate_uid] = candidate
            document_id = candidate.get("document_id")
            by_document_local_id.setdefault((document_id, candidate_id), candidate)
            hierarchy = candidate.get("hierarchy") or {}
            for field in ("section_id", "paragraph_id"):
                value = hierarchy.get(field)
                expected_level = "section" if field == "section_id" else "paragraph"
                if value is not None and candidate.get("level") == expected_level:
                    by_hierarchy_id[(document_id, field, value)] = candidate

        context = []
        current = chunk
        seen = {chunk.get("chunk_uid", (chunk.get("document_id"), chunk.get("chunk_id")))}
        for depth in range(self.max_parent_depth):
            hierarchy = current.get("hierarchy") or {}
            document_id = current.get("document_id")
            parent = None
            parent_uid = hierarchy.get("parent_chunk_uid")
            if parent_uid is not None:
                parent = by_uid.get(parent_uid)
            if parent is None and hierarchy.get("parent_id") is not None:
                parent_id = hierarchy["parent_id"]
                parent_field = "paragraph_id" if str(parent_id).startswith("paragraph:") else "section_id"
                parent = by_hierarchy_id.get((document_id, parent_field, parent_id))
            if parent is None and hierarchy.get("parent_chunk_id") is not None:
                parent = by_document_local_id.get((document_id, hierarchy["parent_chunk_id"]))
                if parent is None:
                    parent = by_document_local_id.get((None, hierarchy["parent_chunk_id"]))
            if parent is None:
                break

            parent_key = parent.get("chunk_uid", (parent.get("document_id"), parent.get("chunk_id")))
            if parent_key in seen:
                break
            seen.add(parent_key)
            context.append({
                "chunk_id": parent.get("chunk_uid", parent.get("chunk_id")),
                "local_chunk_id": parent.get("chunk_id"),
                "level": parent.get("level", "paragraph"),
                "text": parent.get("text", ""),
                "hierarchy": parent.get("hierarchy", {}),
                "source": parent.get("source", "unknown"),
                "context_only": bool(parent.get("context_only")),
                "depth": depth + 1,
                "reason": "hierarchy_parent",
            })
            current = parent
        return context

    def _filter_tiny_sentences(self, df, chunks):
        chunk_lookup = self._chunk_lookup(chunks)
        keep = []
        filtered = []
        for index, row in df.iterrows():
            chunk_id = self._normalize_chunk_id(row.get("node"))
            chunk = chunk_lookup.get(chunk_id, {})
            if chunk.get("context_only"):
                filtered.append({
                    "chunk_id": chunk.get("chunk_uid", chunk_id),
                    "reason": "context_only_parent",
                })
                continue
            level = str(chunk.get("level", row.get("level", ""))).lower()
            word_count = len(str(chunk.get("text", row.get("text_preview", ""))).split())
            if level == "sentence" and word_count < self.min_sentence_words:
                filtered.append({
                    "chunk_id": chunk.get("chunk_uid", chunk_id),
                    "reason": "tiny_sentence",
                    "word_count": word_count,
                    "min_sentence_words": self.min_sentence_words,
                })
                continue
            keep.append(index)
        return df.loc[keep].copy(), filtered

    def _path_evidence(self, graph, node_name: str, peer_nodes: list[str]) -> list[dict]:
        if graph is None:
            return []
        evidence = []
        for peer in peer_nodes:
            if peer == node_name:
                continue
            try:
                path = list(nx.shortest_path(graph, node_name, peer))
            except Exception:
                continue
            if 2 < len(path) <= 4:
                evidence.append({"path": path, "length": len(path) - 1})
            if len(evidence) >= 3:
                break
        return evidence

    def _chunk_record(self, row, chunk, path_evidence=None, parent_context=None, allocation=None):
        context_expansion: dict[str, object] = {
            "added_parent_count": len(parent_context or []),
            "max_depth": self.max_parent_depth,
        }
        record = {
            "chunk_id": chunk.get("chunk_uid", int(row["chunk_id_resolved"])),
            "community": int(row.get("community", -1)),
            "rank": int(row.get("rank", 0)) if pd.notna(row.get("rank", 0)) else 0,
            "composite_score": float(row["composite_score"]),
            "path_aware_score": float(row.get("path_aware_score", row["composite_score"])),
            "text": chunk.get("text", row.get("text_preview", "")),
            "text_preview": row.get("text_preview", ""),
            "level": chunk.get("level", "paragraph"),
            "hierarchy": chunk.get("hierarchy", {"level": chunk.get("level", "paragraph")}),
            "layout": chunk.get("layout", {"kind": chunk.get("level", "paragraph")}),
            "source": chunk.get("source", "unknown"),
            "path_evidence": path_evidence or [],
            "parent_context": parent_context or [],
            "context_expansion": context_expansion,
        }
        if chunk.get("parent_context_status"):
            context_expansion["status"] = chunk["parent_context_status"]
        if chunk.get("document_id") is not None:
            record["document_id"] = chunk["document_id"]
            record["local_chunk_id"] = chunk.get("chunk_id")
        if allocation is not None:
            record["allocation"] = allocation
        return record

    @staticmethod
    def _finite(value, default=0.0):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return default
        return value if math.isfinite(value) else default

    @classmethod
    def _normalized(cls, values):
        bounded = [max(0.0, cls._finite(value)) for value in values]
        maximum = max(bounded, default=0.0)
        return [value / maximum if maximum else 0.0 for value in bounded]

    @staticmethod
    def _text_tokens(text):
        return set(re.findall(r"[\w']+", str(text).casefold()))

    @staticmethod
    def _novelty(tokens, selected_tokens):
        if not tokens:
            return 1.0
        overlap = max(
            (len(tokens & other) / len(tokens | other) for other in selected_tokens if tokens | other),
            default=0.0,
        )
        return 1.0 - overlap

    def _relation_support(self, graph, node_name):
        if graph is None or not graph.has_node(node_name):
            return 0.0
        support = 0.0
        for entity in graph.neighbors(node_name):
            for peer in graph.neighbors(entity):
                if peer == node_name:
                    continue
                edge = graph.get_edge_data(entity, peer, default={})
                if edge.get("edge_type") != "entity_relation":
                    continue
                if (
                    edge.get("evidence_type") == "verified"
                    or edge.get("verification_state") == "verified"
                ):
                    support += max(1.0, self._finite(edge.get("evidence_count"), 1.0))
        return support

    def _path_values(self, row, chunk):
        for key in ("normalized_path_score", "path_score"):
            value = row.get(key, None)
            if value is None or pd.isna(value):
                value = chunk.get(key, None)
            if value is None or pd.isna(value):
                continue
            return self._finite(value), True
        return 0.0, False

    @staticmethod
    def _section_key(chunk):
        hierarchy = chunk.get("hierarchy") or {}
        return (
            hierarchy.get("section_id")
            or hierarchy.get("section")
            or hierarchy.get("section_title")
            or ""
        )

    def _character_cost(self, chunk, row, parent_context, path_evidence):
        metadata = {
            "chunk_id": chunk.get("chunk_uid", chunk.get("chunk_id", row["chunk_id_resolved"])),
            "community": int(row.get("community", -1)),
            "rank": int(row.get("rank", 0)) if pd.notna(row.get("rank", 0)) else 0,
            "level": chunk.get("level", "paragraph"),
        }
        return (
            len(str(chunk.get("text", row.get("text_preview", ""))))
            + sum(len(str(item.get("text", ""))) for item in parent_context)
            + len(json.dumps(path_evidence, sort_keys=True, ensure_ascii=False))
            + len(json.dumps(metadata, sort_keys=True, ensure_ascii=False))
        )

    def _community_allocations(self, candidates, protected_reserves=None):
        protected_reserves = protected_reserves or {}
        grouped = {}
        for candidate in candidates:
            grouped.setdefault(candidate["community"], []).append(candidate)

        communities = []
        for community_id, members in sorted(grouped.items()):
            unique_evidence = len({member["text"].casefold() for member in members if member["text"]})
            section_diversity = len({member["section"] for member in members if member["section"]})
            raw = {
                "query_similarity": max((member["query_raw"] for member in members), default=0.0),
                "retrieval_mass": sum(member["retrieval_raw"] for member in members),
                "graph_support": sum(member["graph_raw"] for member in members) / len(members),
                "relation_support": sum(member["relation_raw"] for member in members) / len(members),
                "unique_evidence_coverage": float(unique_evidence),
                "section_diversity": float(section_diversity),
            }
            communities.append({
                "community_id": community_id,
                "members": members,
                "raw": raw,
                "query_protected_reserve_characters": max(
                    0, int(protected_reserves.get(community_id, 0))
                ),
            })

        metric_names = (
            "query_similarity",
            "retrieval_mass",
            "graph_support",
            "relation_support",
            "unique_evidence_coverage",
            "section_diversity",
        )
        normalized = {
            name: self._normalized([item["raw"][name] for item in communities])
            for name in metric_names
        }
        weights = {
            "query_similarity": 0.25,
            "retrieval_mass": 0.20,
            "graph_support": 0.20,
            "relation_support": 0.15,
            "unique_evidence_coverage": 0.10,
            "section_diversity": 0.10,
        }
        for index, item in enumerate(communities):
            signals = {name: normalized[name][index] for name in metric_names}
            item["signals"] = signals
            item["importance"] = sum(weights[name] * signals[name] for name in metric_names)
            item["query_protected"] = any(member["query_protected"] for member in item["members"])
            # Older collections may not expose retrieval scores.  Strong graph
            # or verified-relation evidence remains eligible in that case.
            item["relevant"] = (
                signals["query_similarity"] >= self.relevance_floor
                or signals["retrieval_mass"] >= self.relevance_floor
                or signals["graph_support"] >= max(self.relevance_floor, 0.2)
                or signals["relation_support"] > 0.0
                or item["query_protected"]
            )
            item["reason"] = "eligible" if item["relevant"] else "below_relevance_floor"
            item["allocated_characters"] = 0

        eligible = [item for item in communities if item["relevant"]]
        if not eligible or not self.context_char_budget:
            return communities

        per_community_cap = min(
            self.max_community_chars,
            int(self.context_char_budget * self.max_community_share),
        )
        reserved_characters = sum(
            item["query_protected_reserve_characters"] for item in eligible
        )
        minimum = min(
            self.min_community_chars,
            per_community_cap,
            (self.context_char_budget - reserved_characters) // len(eligible),
        )
        for item in eligible:
            reserve = item["query_protected_reserve_characters"]
            item["allocated_characters"] = max(minimum, reserve)
            item["query_protected_budget_override"] = reserve > per_community_cap

        remaining = self.context_char_budget - sum(
            item["allocated_characters"] for item in eligible
        )
        total_importance = sum(item["importance"] for item in eligible)
        ordered = sorted(eligible, key=lambda item: (-item["importance"], item["community_id"]))
        for item in ordered:
            share = item["importance"] / total_importance if total_importance else 1 / len(ordered)
            allocation_cap = max(
                per_community_cap, item["query_protected_reserve_characters"]
            )
            additional = min(
                allocation_cap - item["allocated_characters"],
                int(remaining * share),
            )
            item["allocated_characters"] += max(0, additional)

        remaining = self.context_char_budget - sum(item["allocated_characters"] for item in eligible)
        while remaining > 0:
            progressed = False
            for item in ordered:
                allocation_cap = max(
                    per_community_cap, item["query_protected_reserve_characters"]
                )
                if item["allocated_characters"] >= allocation_cap:
                    continue
                item["allocated_characters"] += 1
                remaining -= 1
                progressed = True
                if not remaining:
                    break
            if not progressed:
                break
        return communities

    def _candidate_score(self, candidate, selected_tokens, path_available):
        weights = {
            "relevance": 0.45,
            "graph_support": 0.25,
            "relation_support": 0.15,
            "path_support": 0.15,
        }
        if not path_available:
            weights.pop("path_support")
        total_weight = sum(weights.values())
        base_score = sum(
            weights[name] * candidate["signals"][name] for name in weights
        ) / total_weight
        novelty = self._novelty(candidate["tokens"], selected_tokens)
        return base_score * novelty, novelty, base_score

    def _reserve_query_protected_candidates(self, candidates):
        """Reserve total-budget space for protected retrieval hits before ranking."""
        remaining = self.context_char_budget
        reserves = {}
        rejected = []
        protected = sorted(
            (item for item in candidates if item["query_protected"]),
            key=lambda item: (item["rank"], str(item["node"])),
        )
        for candidate in protected:
            cost = candidate["character_cost"]
            if cost <= remaining:
                candidate["query_protection_reservation"] = "reserved"
                reserves[candidate["community"]] = (
                    reserves.get(candidate["community"], 0) + cost
                )
                remaining -= cost
                continue

            candidate["query_protection_reservation"] = "unavailable"
            rejected.append({
                "chunk_id": candidate["chunk_id"],
                "community_id": candidate["community"],
                "character_cost": cost,
                "query_protected": True,
                "reason": (
                    "query_protected_exceeds_total_budget"
                    if cost > self.context_char_budget
                    else "query_protected_reserve_exhausted"
                ),
                "remaining_characters": remaining,
                "safety_action": "not_selected_to_preserve_character_budget",
            })
        return reserves, rejected

    def select_top_chunks(self, ranked_df: pd.DataFrame, chunks, graph=None):
        empty_allocation = {
            "strategy": "adaptive_character_budget",
            "character_budget": self.context_char_budget,
            "consumed_characters": 0,
            "remaining_characters": self.context_char_budget,
            "path_signal_status": "unavailable",
            "communities": [],
            "selected_chunks": [],
            "rejected_chunks": [],
        }
        if ranked_df.empty:
            return {
                "selection_strategy": "path_aware",
                "global_top_chunks": [],
                "communities": [],
                "filtered_chunks": [],
                "context_allocation": empty_allocation,
            }

        df = ranked_df.copy()
        df = df[df["type"] == "chunk"].copy()
        df = df[df["composite_score"] >= self.min_score].copy()

        if df.empty:
            return {
                "selection_strategy": "path_aware",
                "global_top_chunks": [],
                "communities": [],
                "filtered_chunks": [],
                "context_allocation": empty_allocation,
            }

        df["chunk_id_resolved"] = df["node"].apply(self._normalize_chunk_id)
        df = df[df["chunk_id_resolved"].notna()].copy()
        df["chunk_id_resolved"] = df["chunk_id_resolved"].astype(int)
        prefilter_df = df
        df, filtered_chunks = self._filter_tiny_sentences(df, chunks)
        filtered_rows = [
            row
            for index, row in prefilter_df.iterrows()
            if index not in df.index
        ]

        chunk_lookup = self._chunk_lookup(chunks)
        grouped_nodes = {
            community: group["node"].tolist()
            for community, group in df.groupby("community", sort=True)
        }
        vector_only = bool(
            graph is not None
            and getattr(graph, "graph", {}).get("vector_only")
        )
        candidates = []
        path_available = False
        for _, row in df.iterrows():
            chunk = chunk_lookup.get(row["chunk_id_resolved"], {})
            path_value, has_path_value = self._path_values(row, chunk)
            path_available = path_available or has_path_value
            parent_context = self._parent_context(chunk, chunks)
            path_evidence = self._path_evidence(
                graph,
                row["node"],
                grouped_nodes.get(row["community"], []),
            )
            chunk_id = chunk.get("chunk_uid", int(row["chunk_id_resolved"]))
            query_raw = self._finite(chunk.get("query_similarity", chunk.get("score", 0)))
            candidates.append({
                "chunk_id": chunk_id,
                "node": row["node"],
                "community": int(row.get("community", -1)),
                "rank": int(row.get("rank", 0)) if pd.notna(row.get("rank", 0)) else 0,
                "row": row,
                "chunk": chunk,
                "text": str(chunk.get("text", row.get("text_preview", ""))),
                "tokens": self._text_tokens(chunk.get("text", row.get("text_preview", ""))),
                "section": self._section_key(chunk),
                "query_raw": query_raw,
                "retrieval_raw": self._finite(chunk.get("score", query_raw)),
                "graph_raw": 0.0 if vector_only else self._finite(
                    row.get("composite_score", 0)
                ),
                "relation_raw": self._relation_support(graph, row["node"]),
                "path_raw": path_value,
                "query_protected": bool(
                    chunk.get("query_protected")
                    or row.get("query_protected", False)
                    or (graph is not None and graph.has_node(row["node"])
                        and graph.nodes[row["node"]].get("query_protected"))
                ),
                "parent_context": parent_context,
                "path_evidence": path_evidence,
                "character_cost": self._character_cost(
                    chunk, row, parent_context, path_evidence
                ),
            })

        signal_sources = (
            ("relevance", "query_raw"),
            ("graph_support", "graph_raw"),
            ("relation_support", "relation_raw"),
            ("path_support", "path_raw"),
        )
        signal_maxima = {
            source: max(
                (max(0.0, self._finite(item[source])) for item in candidates),
                default=0.0,
            )
            for _, source in signal_sources
        }
        for name, source in signal_sources:
            for candidate, value in zip(
                candidates,
                self._normalized([item[source] for item in candidates]),
            ):
                candidate.setdefault("signals", {})[name] = value

        prefilter_rejected = []
        for row, filtered in zip(filtered_rows, filtered_chunks):
            chunk = chunk_lookup.get(row["chunk_id_resolved"], {})
            path_value, _ = self._path_values(row, chunk)
            parent_context = self._parent_context(chunk, chunks)
            path_evidence = self._path_evidence(
                graph,
                row["node"],
                grouped_nodes.get(row["community"], []),
            )
            raw_signals = {
                "relevance": self._finite(
                    chunk.get("query_similarity", chunk.get("score", 0))
                ),
                "graph_support": self._finite(row.get("composite_score", 0)),
                "relation_support": self._relation_support(graph, row["node"]),
                "path_support": path_value,
            }
            signals = {
                name: min(1.0, max(0.0, raw_signals[name]) / signal_maxima[source])
                if signal_maxima[source] else 0.0
                for name, source in signal_sources
            }
            prefilter_rejected.append({
                **filtered,
                "community_id": int(row.get("community", -1)),
                "character_cost": self._character_cost(
                    chunk, row, parent_context, path_evidence
                ),
                "signals": signals,
            })

        protected_reserves, protected_rejected = self._reserve_query_protected_candidates(candidates)
        candidates = [
            item for item in candidates
            if item.get("query_protection_reservation") != "unavailable"
        ]
        allocation_communities = self._community_allocations(candidates, protected_reserves)
        selected = []
        selected_tokens = []
        rejected = prefilter_rejected + protected_rejected
        selection_order = 0

        for allocation in sorted(
            allocation_communities,
            key=lambda item: (-item["importance"], item["community_id"]),
        ):
            members = sorted(
                allocation["members"],
                key=lambda item: (item["rank"], str(item["node"])),
            )
            if not allocation["relevant"]:
                rejected.extend({
                    "chunk_id": item["chunk_id"],
                    "community_id": item["community"],
                    "reason": "below_relevance_floor",
                    "character_cost": item["character_cost"],
                } for item in members)
                continue

            community_consumed = 0
            remaining = list(members)
            while remaining:
                scored = []
                for candidate in remaining:
                    marginal_gain, novelty, base_score = self._candidate_score(
                        candidate, selected_tokens, path_available
                    )
                    scored.append((candidate, marginal_gain, novelty, base_score))
                candidate, marginal_gain, novelty, base_score = max(
                    scored,
                    key=lambda item: (
                        item[0]["query_protected"], item[1], -item[0]["rank"], str(item[0]["node"])
                    ),
                )
                remaining.remove(candidate)
                diagnostic = {
                    "chunk_id": candidate["chunk_id"],
                    "community_id": candidate["community"],
                    "character_cost": candidate["character_cost"],
                    "signals": {
                        **candidate["signals"],
                        "novelty": novelty,
                        "base_score": base_score,
                        "marginal_gain": marginal_gain,
                    },
                }
                if not candidate["query_protected"] and marginal_gain < self.min_marginal_gain:
                    rejected.append({**diagnostic, "reason": "redundant_evidence"})
                    continue
                if community_consumed + candidate["character_cost"] > allocation["allocated_characters"]:
                    rejected.append({**diagnostic, "reason": "community_budget_exhausted"})
                    continue

                selection_order += 1
                selection_reason = (
                    "query_protected" if candidate["query_protected"]
                    else "minimum_coverage" if community_consumed == 0
                    else "highest_marginal_gain"
                )
                allocation_record = {
                    **diagnostic,
                    "selection_order": selection_order,
                    "selection_reason": selection_reason,
                }
                if candidate["query_protected"]:
                    allocation_record["query_protection_reservation"] = (
                        candidate.get("query_protection_reservation", "not_required")
                    )
                candidate["row"] = candidate["row"].copy()
                candidate["row"]["path_aware_score"] = base_score
                record = self._chunk_record(
                    candidate["row"],
                    candidate["chunk"],
                    candidate["path_evidence"],
                    candidate["parent_context"],
                    allocation_record,
                )
                selected.append({"candidate": candidate, "record": record, "diagnostic": allocation_record})
                selected_tokens.append(candidate["tokens"])
                community_consumed += candidate["character_cost"]

            allocation["consumed_characters"] = community_consumed
            allocation["selected_count"] = sum(
                1 for item in selected if item["candidate"]["community"] == allocation["community_id"]
            )

        selected_by_community = {}
        for item in selected:
            selected_by_community.setdefault(item["candidate"]["community"], []).append(item["record"])
        communities = [
            {
                "community_id": int(community_id),
                "num_selected_chunks": len(selected_by_community[community_id]),
                "chunks": selected_by_community[community_id],
            }
            for community_id in sorted(selected_by_community)
        ]
        global_top_chunks = [item["record"] for item in selected]
        consumed = sum(item["diagnostic"]["character_cost"] for item in selected)
        context_allocation = {
            "strategy": "adaptive_character_budget",
            "character_budget": self.context_char_budget,
            "consumed_characters": consumed,
            "remaining_characters": self.context_char_budget - consumed,
            "path_signal_status": "available" if path_available else "unavailable",
            "communities": [
                {
                    "community_id": item["community_id"],
                    "importance": item["importance"],
                    "signals": item["signals"],
                    "allocated_characters": item["allocated_characters"],
                    "query_protected_reserve_characters": item[
                        "query_protected_reserve_characters"
                    ],
                    "query_protected_budget_override": item.get(
                        "query_protected_budget_override", False
                    ),
                    "consumed_characters": item.get("consumed_characters", 0),
                    "selected_count": item.get("selected_count", 0),
                    "reason": item["reason"],
                }
                for item in sorted(allocation_communities, key=lambda item: item["community_id"])
            ],
            "selected_chunks": [item["diagnostic"] for item in selected],
            "rejected_chunks": rejected,
        }

        return {
            "selection_strategy": "path_aware",
            "global_top_chunks": global_top_chunks,
            "communities": communities,
            "filtered_chunks": filtered_chunks,
            "context_allocation": context_allocation,
        }

    def save_pruned_json(self, pruned_result, output_path="output/pruned_summary_context.json"):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with open(out, "w", encoding="utf-8") as f:
            json.dump(pruned_result, f, indent=2, ensure_ascii=False)

        print(f"✅ Pruned summary context saved: {out}")
        return str(out)

    def save_pruned_csv(self, pruned_result, output_path="output/pruned_summary_context.csv"):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        rows = []
        for community in pruned_result.get("communities", []):
            for chunk in community.get("chunks", []):
                rows.append({
                    "community_id": community["community_id"],
                    "chunk_id": chunk["chunk_id"],
                    "rank": chunk["rank"],
                    "composite_score": chunk["composite_score"],
                    "path_aware_score": chunk.get("path_aware_score", chunk["composite_score"]),
                    "level": chunk["level"],
                    "source": chunk["source"],
                    "parent_context_ids": ",".join(str(item.get("chunk_id")) for item in chunk.get("parent_context", [])),
                    "text_preview": chunk["text_preview"],
                    "text": chunk["text"]
                })

        df = pd.DataFrame(rows)
        df.to_csv(out, index=False)

        print(f"✅ Pruned summary CSV saved: {out}")
        return str(out)
