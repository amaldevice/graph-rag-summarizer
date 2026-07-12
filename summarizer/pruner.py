# ============================================================
# PRUNER / RE-RANKER
# Select top-k chunk nodes per community for summarization stage
# ============================================================

import json
from pathlib import Path

import networkx as nx
import pandas as pd


class SummaryPruner:
    def __init__(self, top_k_per_community=3, top_k_global=10, min_score=0.0, min_sentence_words=8, max_parent_depth=2):
        self.top_k_per_community = top_k_per_community
        self.top_k_global = top_k_global
        self.min_score = min_score
        self.min_sentence_words = min_sentence_words
        self.max_parent_depth = max_parent_depth

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

    def _chunk_record(self, row, chunk, path_evidence=None, parent_context=None):
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
        return record

    def select_top_chunks(self, ranked_df: pd.DataFrame, chunks, graph=None):
        if ranked_df.empty:
            return {
                "selection_strategy": "path_aware",
                "global_top_chunks": [],
                "communities": [],
                "filtered_chunks": [],
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
            }

        df["chunk_id_resolved"] = df["node"].apply(self._normalize_chunk_id)
        df = df[df["chunk_id_resolved"].notna()].copy()
        df["chunk_id_resolved"] = df["chunk_id_resolved"].astype(int)
        node_names = df["node"].tolist()
        df["path_signal"] = df["node"].apply(
            lambda node: min(len(self._path_evidence(graph, node, node_names)), 3) / 3
        )
        df["retrieval_score"] = df["chunk_id_resolved"].apply(
            lambda cid: float((self._chunk_lookup(chunks).get(cid, {}) or {}).get("score") or 0)
        )
        df["path_aware_score"] = (
            (df["composite_score"].astype(float) * 0.7)
            + (df["retrieval_score"].astype(float) * 0.2)
            + (df["path_signal"].astype(float) * 0.1)
        )

        df, filtered_chunks = self._filter_tiny_sentences(df, chunks)
        if df.empty:
            return {
                "selection_strategy": "path_aware",
                "global_top_chunks": [],
                "communities": [],
                "filtered_chunks": filtered_chunks,
            }

        chunk_lookup = self._chunk_lookup(chunks)

        global_top = (
            df.sort_values("path_aware_score", ascending=False)
              .head(self.top_k_global)
        )

        global_top_chunks = []
        for _, row in global_top.iterrows():
            chunk = chunk_lookup.get(row["chunk_id_resolved"], {})
            global_top_chunks.append(self._chunk_record(
                row,
                chunk,
                self._path_evidence(graph, row["node"], node_names),
                self._parent_context(chunk, chunks),
            ))

        communities = []
        grouped = df.sort_values(["community", "path_aware_score"], ascending=[True, False]).groupby("community")

        for community_id, group in grouped:
            top_rows = group.head(self.top_k_per_community)
            selected_chunks = []

            for _, row in top_rows.iterrows():
                chunk = chunk_lookup.get(row["chunk_id_resolved"], {})
                selected_chunks.append(self._chunk_record(
                    row,
                    chunk,
                    self._path_evidence(graph, row["node"], group["node"].tolist()),
                    self._parent_context(chunk, chunks),
                ))

            communities.append({
                "community_id": int(community_id),
                "num_selected_chunks": len(selected_chunks),
                "chunks": selected_chunks
            })

        return {
            "selection_strategy": "path_aware",
            "global_top_chunks": global_top_chunks,
            "communities": communities,
            "filtered_chunks": filtered_chunks,
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
