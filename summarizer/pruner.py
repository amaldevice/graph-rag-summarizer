# ============================================================
# PRUNER / RE-RANKER
# Select top-k chunk nodes per community for summarization stage
# ============================================================

import json
from pathlib import Path

import networkx as nx
import pandas as pd


class SummaryPruner:
    def __init__(self, top_k_per_community=3, top_k_global=10, min_score=0.0):
        self.top_k_per_community = top_k_per_community
        self.top_k_global = top_k_global
        self.min_score = min_score

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
            lookup[chunk_id] = chunk
            lookup[idx] = chunk
        return lookup

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

    def _chunk_record(self, row, chunk, path_evidence=None):
        return {
            "chunk_id": int(row["chunk_id_resolved"]),
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
        }

    def select_top_chunks(self, ranked_df: pd.DataFrame, chunks, graph=None):
        if ranked_df.empty:
            return {
                "selection_strategy": "path_aware",
                "global_top_chunks": [],
                "communities": []
            }

        df = ranked_df.copy()
        df = df[df["type"] == "chunk"].copy()
        df = df[df["composite_score"] >= self.min_score].copy()

        if df.empty:
            return {
                "selection_strategy": "path_aware",
                "global_top_chunks": [],
                "communities": []
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
                ))

            communities.append({
                "community_id": int(community_id),
                "num_selected_chunks": len(selected_chunks),
                "chunks": selected_chunks
            })

        return {
            "selection_strategy": "path_aware",
            "global_top_chunks": global_top_chunks,
            "communities": communities
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
                    "text_preview": chunk["text_preview"],
                    "text": chunk["text"]
                })

        df = pd.DataFrame(rows)
        df.to_csv(out, index=False)

        print(f"✅ Pruned summary CSV saved: {out}")
        return str(out)
