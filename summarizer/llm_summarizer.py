# ============================================================
# LLM SUMMARIZER
# Map-style summarization per community using Groq
# ============================================================

import json
import os
import time
from pathlib import Path
from typing import Dict, List

try:
    from groq import Groq
except ImportError:
    Groq = None


class LLMSummarizer:
    def __init__(self, groq_api_key=None, groq_model="llama-3.1-8b-instant"):
        self.groq_model = groq_model
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        self.client = None

        if self.groq_api_key and Groq is not None:
            self.client = Groq(api_key=self.groq_api_key)

    def _require_client(self):
        if self.client is None:
            raise RuntimeError(
                "Groq client is not available. Ensure package 'groq' is installed and GROQ_API_KEY is set."
            )

    def summarize_prompt(self, prompt: str, max_retries: int = 4) -> str:
        self._require_client()
        last_error = None

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.groq_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a precise summarization assistant. Return only the summary text."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.2,
                    max_completion_tokens=400
                )

                content = response.choices[0].message.content
                return content.strip()

            except Exception as e:
                last_error = e
                error_text = str(e).lower()

                if "429" in error_text or "rate" in error_text or "limit" in error_text:
                    time.sleep(min(2 ** attempt, 20))
                    continue

                if attempt < max_retries - 1:
                    time.sleep(1.5)
                    continue

        raise RuntimeError(f"Groq summarization failed: {last_error}")

    def summarize_communities(self, community_prompts: List[Dict]) -> List[Dict]:
        summaries = []

        for item in community_prompts:
            community_id = item.get("community_id", -1)
            prompt = item.get("prompt", "")
            chunk_ids = item.get("chunk_ids", [])
            num_chunks = item.get("num_chunks", 0)

            summary_text = self.summarize_prompt(prompt)

            summaries.append({
                "community_id": community_id,
                "num_chunks": num_chunks,
                "chunk_ids": chunk_ids,
                "summary": summary_text
            })

        return summaries

    def save_map_summaries_json(self, summaries: List[Dict], output_path="output/community_map_summaries.json"):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with open(out, "w", encoding="utf-8") as f:
            json.dump(summaries, f, indent=2, ensure_ascii=False)

        print(f"✅ Community summaries saved: {out}")
        return str(out)

    def save_map_summaries_txt(self, summaries: List[Dict], output_path="output/community_map_summaries.txt"):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with open(out, "w", encoding="utf-8") as f:
            for item in summaries:
                f.write(f"=== COMMUNITY {item['community_id']} ===\n")
                f.write(f"Chunks: {item['chunk_ids']}\n")
                f.write(item["summary"].strip() + "\n\n")

        print(f"✅ Community summaries TXT saved: {out}")
        return str(out)
