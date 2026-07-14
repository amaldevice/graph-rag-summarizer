import json

import pandas as pd

from graph.graph_analyzer import GraphAnalyzer


def test_graph_summary_exposes_relation_extraction_mode(tmp_path):
    output_path = tmp_path / "graph_summary.json"
    ranked = pd.DataFrame([{
        "node": "chunk_0",
        "type": "chunk",
        "community": 0,
        "degree": 0.0,
        "betweenness": 0.0,
        "eigenvector": 0.0,
        "pagerank": 1.0,
        "composite_score": 0.25,
        "text_preview": "evidence",
        "rank": 1,
    }])

    GraphAnalyzer().save_summary_json(
        ranked,
        {0: ["chunk_0"]},
        0.1,
        output_path,
        relation_extraction_mode="llm-enhanced",
    )

    summary = json.loads(output_path.read_text(encoding="utf-8"))

    assert summary["relation_extraction"] == {"mode": "llm-enhanced"}
