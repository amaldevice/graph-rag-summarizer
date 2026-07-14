# ============================================================
# LLM SUMMARIZER
# Map-style summarization per community using provider router
# ============================================================

import json
from pathlib import Path
from typing import Dict, List, Optional

from summarizer.provider_router import ProviderRouter, create_session


class LLMSummarizer:
    def __init__(self, session: Optional[ProviderRouter] = None):
        self.session = session or create_session()

    def summarize_prompt(self, prompt: str) -> str:
        system_prompt = "You are a precise summarization assistant. Return only the summary text."
        return self.session.call_llm(system_prompt, prompt)

    def summarize_communities(self, community_prompts: List[Dict]) -> List[Dict]:
        summaries = []

        for item in community_prompts:
            community_id = item.get("community_id", -1)
            prompt = item.get("prompt", "")
            chunk_ids = item.get("chunk_ids", [])
            num_chunks = item.get("num_chunks", 0)

            provider_safety = item.get("provider_safety", {})
            blocked = isinstance(provider_safety, dict) and provider_safety.get("status") == "blocked"
            summary_text = "" if blocked else self.summarize_prompt(prompt)

            summary = {
                "community_id": community_id,
                "num_chunks": num_chunks,
                "chunk_ids": chunk_ids,
                "summary": summary_text,
            }
            if blocked:
                summary["skip_reason"] = "provider_token_budget_exceeded"
            summaries.append(summary)

        return summaries

    def save_map_summaries_json(
        self, summaries: List[Dict], output_path="output/community_map_summaries.json"
    ):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with open(out, "w", encoding="utf-8") as f:
            json.dump(summaries, f, indent=2, ensure_ascii=False)

        print(f"✅ Community summaries saved: {out}")
        return str(out)

    def save_map_summaries_txt(
        self, summaries: List[Dict], output_path="output/community_map_summaries.txt"
    ):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with open(out, "w", encoding="utf-8") as f:
            for item in summaries:
                f.write(f"=== COMMUNITY {item['community_id']} ===\n")
                f.write(f"Chunks: {item['chunk_ids']}\n")
                f.write(item["summary"].strip() + "\n\n")

        print(f"✅ Community summaries TXT saved: {out}")
        return str(out)
