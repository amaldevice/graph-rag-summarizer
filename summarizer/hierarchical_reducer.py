# ============================================================
# HIERARCHICAL REDUCER
# Reduce community summaries into one final summary
# using the shared provider router session
# ============================================================

import json
from pathlib import Path
from typing import Dict, List, Optional

from summarizer.provider_router import ProviderRouter, create_session


class HierarchicalReducer:
    def __init__(self, session: Optional[ProviderRouter] = None):
        self.session = session or create_session()

    def build_reduce_prompt(
        self,
        community_summaries: List[Dict],
        query: Optional[str] = None,
        style: str = "concise"
    ) -> str:
        query_text = query or "Summarize the overall main idea of the document."

        style_instruction_map = {
            "concise": "Write one concise final summary paragraph.",
            "bullet": "Write a clean bullet-point final summary.",
            "detailed": "Write a detailed final summary that preserves the important points across communities."
        }
        style_instruction = style_instruction_map.get(style, style_instruction_map["concise"])

        blocks = []
        for item in community_summaries:
            blocks.append(
                f"[Community {item.get('community_id', -1)}]\n"
                f"chunk_ids: {item.get('chunk_ids', [])}\n"
                f"summary:\n{item.get('summary', '').strip()}"
            )

        summaries_text = "\n\n".join(blocks) if blocks else "No community summaries available."

        prompt = f"""
You are a scientific document summarization assistant.
Your task is to merge several community-level summaries into one final document summary.

User question / summarization goal:
{query_text}

Important instructions:
- Use only the information from the community summaries below.
- Merge overlapping points.
- Preserve the main contribution, method, and key findings if they are present.
- Do not invent details.
- Keep the final summary coherent and non-redundant.
- {style_instruction}

Community summaries:
{summaries_text}

Return only the final summary text.
""".strip()

        return prompt

    def reduce_summaries(
        self,
        community_summaries: List[Dict],
        query: Optional[str] = None,
        style: str = "concise",
    ) -> Dict:
        prompt = self.build_reduce_prompt(community_summaries, query=query, style=style)
        system_prompt = "You are a precise summarization assistant. Return only the final summary text."

        final_summary = self.session.call_llm(system_prompt, prompt)

        return {
            "query": query or "",
            "num_communities": len(community_summaries),
            "final_summary": final_summary,
            "community_ids": [item.get("community_id", -1) for item in community_summaries],
        }

    def save_final_summary_json(self, result: Dict, output_path="output/final_summary.json"):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"✅ Final summary JSON saved: {out}")
        return str(out)

    def save_final_summary_txt(self, result: Dict, output_path="output/final_summary.txt"):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with open(out, "w", encoding="utf-8") as f:
            f.write(result.get("final_summary", "").strip() + "\n")

        print(f"✅ Final summary TXT saved: {out}")
        return str(out)
