# ============================================================
# PROMPT BUILDER
# Structure-aware prompts for community-level summarization
# ============================================================

import math
from typing import Dict, List, Optional


class PromptBuilder:
    def __init__(
        self,
        max_chars_per_chunk: int = 1200,
        provider_context_token_limit: int = 4096,
        reserved_output_tokens: int = 400,
    ):
        self.max_chars_per_chunk = max_chars_per_chunk
        self.provider_context_token_limit = max(0, int(provider_context_token_limit))
        self.reserved_output_tokens = max(0, int(reserved_output_tokens))

    def _truncate_text(self, text: str) -> str:
        if not isinstance(text, str):
            return ""
        text = text.strip()
        if len(text) <= self.max_chars_per_chunk:
            return text
        return text[: self.max_chars_per_chunk].rstrip() + " ..."

    @staticmethod
    def _estimated_tokens(text: str) -> int:
        """Use a conservative, tokenizer-independent estimate for the safety gate."""
        return math.ceil(len(text) / 3)

    def _provider_safety(self, prompt: str) -> Dict:
        estimated_input_tokens = self._estimated_tokens(prompt)
        available_input_tokens = max(
            0, self.provider_context_token_limit - self.reserved_output_tokens
        )
        return {
            "status": (
                "within_limit"
                if estimated_input_tokens <= available_input_tokens
                else "blocked"
            ),
            "provider_context_token_limit": self.provider_context_token_limit,
            "reserved_output_tokens": self.reserved_output_tokens,
            "estimated_input_tokens": estimated_input_tokens,
            "estimated_total_tokens": estimated_input_tokens + self.reserved_output_tokens,
            "prompt_characters": len(prompt),
        }

    @staticmethod
    def _prompt_budget(pruned_result: Dict, community: Dict, chunks: List[Dict]) -> Dict:
        allocation = pruned_result.get("context_allocation", {})
        if not isinstance(allocation, dict):
            allocation = {}
        community_id = community.get("community_id", -1)
        community_allocation = next(
            (
                item
                for item in allocation.get("communities", [])
                if item.get("community_id") == community_id
            ),
            {},
        )
        selected_character_cost = sum(
            int((chunk.get("allocation") or {}).get("character_cost", len(str(chunk.get("text", "")))))
            for chunk in chunks
        )
        return {
            "selected_chunk_count": len(chunks),
            "selected_character_cost": selected_character_cost,
            "community_character_budget": community_allocation.get("allocated_characters", 0),
            "total_character_budget": allocation.get("character_budget", 0),
        }

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

        def chunk_identity(item):
            document_id = item.get("document_id")
            local_id = item.get("local_chunk_id")
            if document_id is not None and local_id is not None:
                return f"{document_id}:chunk:{local_id}"
            return str(item.get("chunk_uid", item.get("chunk_id")))

        chunk_blocks = []
        selected_chunk_ids = {chunk_identity(chunk) for chunk in chunks}
        seen_parent_ids = set()
        for idx, chunk in enumerate(chunks, start=1):
            text = self._truncate_text(chunk.get("text", ""))
            hierarchy = chunk.get("hierarchy") or {}
            path_evidence = chunk.get("path_evidence") or []
            parent_context = []
            for item in chunk.get("parent_context") or []:
                if item.get("context_only") and item.get("text", "").strip() == chunk.get("text", "").strip():
                    continue
                parent_id = chunk_identity(item)
                if parent_id in selected_chunk_ids or parent_id in seen_parent_ids:
                    continue
                seen_parent_ids.add(parent_id)
                parent_context.append(item)
            parent_context_text = "\n".join(
                f"- [{item.get('level', 'parent')}] {self._truncate_text(item.get('text', ''))}"
                for item in parent_context
            ) or "none"
            chunk_blocks.append(
                f"[Chunk {idx}]\n"
                f"chunk_id: {chunk.get('chunk_id', 'unknown')}\n"
                f"rank: {chunk.get('rank', 'unknown')}\n"
                f"composite_score: {chunk.get('composite_score', 0):.4f}\n"
                f"level: {chunk.get('level', 'paragraph')}\n"
                f"hierarchy_section: {hierarchy.get('section')}\n"
                f"path_evidence: {path_evidence}\n"
                f"parent_context:\n{parent_context_text}\n"
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
            budget = self._prompt_budget(pruned_result, community, chunks)

            prompts.append({
                "community_id": community_id,
                "num_chunks": len(chunks),
                "prompt": prompt_text,
                "chunk_ids": [c.get("chunk_id") for c in chunks],
                "budget": budget,
                "provider_safety": self._provider_safety(prompt_text),
            })

        return prompts
