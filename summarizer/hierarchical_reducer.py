# ============================================================
# HIERARCHICAL REDUCER
# Reduce community summaries into one final summary
# using the shared provider router session
# ============================================================

import json
import math
from pathlib import Path
from typing import Dict, List, Optional

from summarizer.provider_router import ProviderRouter, create_session


class HierarchicalReducer:
    def __init__(
        self,
        session: Optional[ProviderRouter] = None,
        embedder=None,
        raptor_group_size: int = 4,
    ):
        self.session = session or create_session()
        self.embedder = embedder
        self.raptor_group_size = max(2, int(raptor_group_size))

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
- CGM (Community-to-Global Merge): merge community summaries into a grounded global answer.
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

    def _get_embedder(self):
        if self.embedder is None:
            from embedding.embedder import TextEmbedder
            self.embedder = TextEmbedder()
        return self.embedder

    def _embed_summary(self, text: str):
        embedder = self._get_embedder()
        if hasattr(embedder, "embed_text"):
            return embedder.embed_text(text)
        return None

    @staticmethod
    def _cosine_similarity(left, right):
        try:
            left = [float(value) for value in left]
            right = [float(value) for value in right]
        except (TypeError, ValueError):
            return None
        if not left or len(left) != len(right) or not all(
            math.isfinite(value) for value in left + right
        ):
            return None
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return None
        return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)

    @staticmethod
    def _summary_id(item):
        return str(item.get("community_id", item.get("source_id", "")))

    def _similarity_groups(self, summaries: List[Dict]):
        ordered = sorted(summaries, key=self._summary_id)
        vectors = [self._embed_summary(item.get("summary", "")) for item in ordered]
        if any(
            vector is None or self._cosine_similarity(vectors[0], vector) is None
            for vector in vectors
        ):
            return [
                ordered[start:start + self.raptor_group_size]
                for start in range(0, len(ordered), self.raptor_group_size)
            ], "input_order_fallback"

        remaining = list(range(len(ordered)))
        groups = []
        while remaining:
            anchor = remaining.pop(0)
            nearest = sorted(
                remaining,
                key=lambda index: (
                    -similarity if (similarity := self._cosine_similarity(
                        vectors[anchor], vectors[index]
                    )) is not None else 1.0,
                    self._summary_id(ordered[index]),
                ),
            )[:self.raptor_group_size - 1]
            groups.append([ordered[index] for index in [anchor, *nearest]])
            remaining = [index for index in remaining if index not in nearest]
        return groups, "embedding_similarity"

    def _merge_group(self, group: List[Dict], query: Optional[str], style: str, level: int, group_index: int) -> Dict:
        prompt = self.build_reduce_prompt(group, query=query, style=style)
        system_prompt = "You are a precise summarization assistant. Return only the merged summary text."
        summary = self.session.call_llm(system_prompt, prompt)
        return {
            "community_id": f"level_{level}_group_{group_index}",
            "summary": summary,
            "chunk_ids": [cid for item in group for cid in item.get("chunk_ids", [])],
            "source_ids": [item.get("community_id", item.get("source_id")) for item in group],
        }

    def _raptor_reduce(self, community_summaries: List[Dict], query: Optional[str], style: str) -> Dict:
        current = list(community_summaries)
        levels = []
        level = 1
        while len(current) > 1:
            next_level = []
            groups, grouping_strategy = self._similarity_groups(current)
            for group_index, group in enumerate(groups, start=1):
                next_level.append(self._merge_group(group, query, style, level, group_index))
            levels.append({
                "level": level,
                "input_count": len(current),
                "output_count": len(next_level),
                "grouping_strategy": grouping_strategy,
                "groups": [
                    {
                        "group_index": group_index,
                        "source_ids": [item.get("community_id", item.get("source_id")) for item in group],
                    }
                    for group_index, group in enumerate(groups, start=1)
                ],
                "summaries": next_level,
            })
            current = next_level
            level += 1

        final_summary = current[0].get("summary", "") if current else ""
        return {
            "query": query or "",
            "num_communities": len(community_summaries),
            "final_summary": final_summary,
            "community_ids": [item.get("community_id", -1) for item in community_summaries],
            "reduction_strategy": "raptor",
            "reduction_levels": levels,
        }

    def reduce_summaries(
        self,
        community_summaries: List[Dict],
        query: Optional[str] = None,
        style: str = "concise",
    ) -> Dict:
        if len(community_summaries) > self.raptor_group_size:
            return self._raptor_reduce(community_summaries, query=query, style=style)

        prompt = self.build_reduce_prompt(community_summaries, query=query, style=style)
        system_prompt = "You are a precise summarization assistant. Return only the final summary text."

        final_summary = self.session.call_llm(system_prompt, prompt)

        return {
            "query": query or "",
            "num_communities": len(community_summaries),
            "final_summary": final_summary,
            "community_ids": [item.get("community_id", -1) for item in community_summaries],
            "reduction_strategy": "single_merge",
            "reduction_levels": [],
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
