# ============================================================
# GRAPH ANALYZER
# Centrality ranking and outputs for next stage
# ============================================================

import json
from pathlib import Path

import networkx as nx
import pandas as pd


class GraphAnalyzer:
    def analyze(self, G):
        deg = nx.degree_centrality(G)
        bet = nx.betweenness_centrality(G, weight='weight')

        try:
            eig = nx.eigenvector_centrality(G, max_iter=500, weight='weight')
        except Exception:
            eig = {n: 0.0 for n in G.nodes()}

        pr = nx.pagerank(G, weight='weight')

        rows = []
        for node in G.nodes():
            score = (
                deg.get(node, 0)
                + bet.get(node, 0)
                + eig.get(node, 0)
                + pr.get(node, 0)
            ) / 4

            rows.append({
                "node": node,
                "type": G.nodes[node].get("type", "unknown"),
                "community": G.nodes[node].get("community", -1),
                "degree": deg.get(node, 0),
                "betweenness": bet.get(node, 0),
                "eigenvector": eig.get(node, 0),
                "pagerank": pr.get(node, 0),
                "composite_score": score,
                "text_preview": G.nodes[node].get("text", "")
            })

        df = (
            pd.DataFrame(rows)
            .sort_values("composite_score", ascending=False)
            .reset_index(drop=True)
        )
        df["rank"] = range(1, len(df) + 1)
        return df

    def save_ranked_csv(self, df, output_path="output/graph_ranked_nodes.csv"):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        print(f"✅ CSV tersimpan di: {out}")
        return str(out)

    def save_ranked_json(self, df, output_path="output/graph_ranked_nodes.json"):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        records = df.to_dict(orient="records")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)

        print(f"✅ JSON tersimpan di: {out}")
        return str(out)

    def save_summary_json(
        self,
        df,
        communities,
        modularity,
        output_path="output/graph_summary.json"
    ):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        top_nodes = df.head(10).to_dict(orient="records")
        community_summary = []

        for community_id, members in communities.items():
            community_summary.append({
                "community_id": community_id,
                "size": len(members),
                "members": members[:20]
            })

        summary = {
            "modularity": modularity,
            "total_nodes": int(len(df)),
            "total_communities": int(len(communities)),
            "top_nodes": top_nodes,
            "communities": community_summary
        }

        with open(out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        print(f"✅ Summary JSON tersimpan di: {out}")
        return str(out)