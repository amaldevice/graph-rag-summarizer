# ============================================================
# PRUNER / RE-RANKER
# Select top-k chunk nodes per community for summarization stage
# ============================================================

import json
from pathlib import Path

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

    def select_top_chunks(self, ranked_df: pd.DataFrame, chunks):
        if ranked_df.empty:
            return {
                "global_top_chunks": [],
                "communities": []
            }

        df = ranked_df.copy()
        df = df[df["type"] == "chunk"].copy()
        df = df[df["composite_score"] >= self.min_score].copy()

        if df.empty:
            return {
                "global_top_chunks": [],
                "communities": []
            }

        df["chunk_id_resolved"] = df["node"].apply(self._normalize_chunk_id)
        df = df[df["chunk_id_resolved"].notna()].copy()
        df["chunk_id_resolved"] = df["chunk_id_resolved"].astype(int)

        chunk_lookup = self._chunk_lookup(chunks)

        global_top = (
            df.sort_values("composite_score", ascending=False)
              .head(self.top_k_global)
        )

        global_top_chunks = []
        for _, row in global_top.iterrows():
            chunk = chunk_lookup.get(row["chunk_id_resolved"], {})
            global_top_chunks.append({
                "chunk_id": int(row["chunk_id_resolved"]),
                "community": int(row.get("community", -1)),
                "rank": int(row.get("rank", 0)) if pd.notna(row.get("rank", 0)) else 0,
                "composite_score": float(row["composite_score"]),
                "text": chunk.get("text", row.get("text_preview", "")),
                "text_preview": row.get("text_preview", ""),
                "level": chunk.get("level", "paragraph"),
                "source": chunk.get("source", "unknown")
            })

        communities = []
        grouped = df.sort_values(["community", "composite_score"], ascending=[True, False]).groupby("community")

        for community_id, group in grouped:
            top_rows = group.head(self.top_k_per_community)
            selected_chunks = []

            for _, row in top_rows.iterrows():
                chunk = chunk_lookup.get(row["chunk_id_resolved"], {})
                selected_chunks.append({
                    "chunk_id": int(row["chunk_id_resolved"]),
                    "rank": int(row.get("rank", 0)) if pd.notna(row.get("rank", 0)) else 0,
                    "composite_score": float(row["composite_score"]),
                    "text": chunk.get("text", row.get("text_preview", "")),
                    "text_preview": row.get("text_preview", ""),
                    "level": chunk.get("level", "paragraph"),
                    "source": chunk.get("source", "unknown")
                })

            communities.append({
                "community_id": int(community_id),
                "num_selected_chunks": len(selected_chunks),
                "chunks": selected_chunks
            })

        return {
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
                    "level": chunk["level"],
                    "source": chunk["source"],
                    "text_preview": chunk["text_preview"],
                    "text": chunk["text"]
                })

        df = pd.DataFrame(rows)
        df.to_csv(out, index=False)

        print(f"✅ Pruned summary CSV saved: {out}")
        return str(out)
