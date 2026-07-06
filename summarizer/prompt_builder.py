# ============================================================
# PROMPT BUILDER
# Structure-aware prompts for community-level summarization
# ============================================================

from typing import Dict, List, Optional


class PromptBuilder:
    def __init__(self, max_chars_per_chunk: int = 1200):
        self.max_chars_per_chunk = max_chars_per_chunk

    def _truncate_text(self, text: str) -> str:
        if not isinstance(text, str):
            return ""
        text = text.strip()
        if len(text) <= self.max_chars_per_chunk:
            return text
        return text[: self.max_chars_per_chunk].rstrip() + " ..."

    def build_community_prompt(
        self,
        community_id: int,
        chunks: List[Dict],
        query: Optional[str] = None,
        style: str = "concise"
    ) -> str:
        query_text = query or "Summarize the main ideas in this community."

        style_instruction_map = {
            "concise": "Write a concise paragraph summary with the most important ideas only.",
            "bullet": "Write a bullet-point summary with the most important ideas only.",
            "detailed": "Write a detailed but faithful summary, preserving important claims and context."
        }
        style_instruction = style_instruction_map.get(
            style,
            style_instruction_map["concise"]
        )

        chunk_blocks = []
        for idx, chunk in enumerate(chunks, start=1):
            text = self._truncate_text(chunk.get("text", ""))
            hierarchy = chunk.get("hierarchy") or {}
            path_evidence = chunk.get("path_evidence") or []
            chunk_blocks.append(
                f"[Chunk {idx}]\n"
                f"chunk_id: {chunk.get('chunk_id', 'unknown')}\n"
                f"rank: {chunk.get('rank', 'unknown')}\n"
                f"composite_score: {chunk.get('composite_score', 0):.4f}\n"
                f"level: {chunk.get('level', 'paragraph')}\n"
                f"hierarchy_section: {hierarchy.get('section')}\n"
                f"path_evidence: {path_evidence}\n"
                f"text:\n{text}"
            )

        chunk_context = "\n\n".join(chunk_blocks) if chunk_blocks else "No chunk context provided."

        prompt = f"""
You are a scientific document summarization assistant.
Your task is to summarize one graph community extracted from a long document.

User question / summarization goal:
{query_text}

Community ID:
{community_id}

Important instructions:
- NAP (Node-Aware Prompt): treat each chunk as a graph node with rank, hierarchy, and path evidence.
- CAP (Community-Aware Prompt): summarize only Community {community_id} and explain shared ideas across its selected nodes.
- CGM (Community-to-Global Merge): write this community summary so it can be merged into a global final answer later.
- Use only the information provided in the chunks below.
- Focus on the most central and repeated ideas.
- Preserve factual meaning.
- Do not invent details that are not supported by the chunks.
- If multiple chunks repeat the same idea, merge them into one coherent point.
- Prefer content from higher-ranked chunks when deciding what is most salient.
- {style_instruction}

Context chunks:
{chunk_context}

Return only the summary text.
""".strip()

        return prompt

    def build_all_community_prompts(
        self,
        pruned_result: Dict,
        query: Optional[str] = None,
        style: str = "concise"
    ) -> List[Dict]:
        prompts = []

        for community in pruned_result.get("communities", []):
            community_id = community.get("community_id", -1)
            chunks = community.get("chunks", [])
            prompt_text = self.build_community_prompt(
                community_id=community_id,
                chunks=chunks,
                query=query,
                style=style
            )

            prompts.append({
                "community_id": community_id,
                "num_chunks": len(chunks),
                "prompt": prompt_text,
                "chunk_ids": [c.get("chunk_id") for c in chunks]
            })

        return prompts
