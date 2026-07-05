# ============================================================
# ENTITY EXTRACTOR
# Hybrid Entity Extraction: SpaCy NER + filtering + Groq relation mining
# ============================================================

from collections import defaultdict
import json
import os
import re
import time

import spacy
from openai import OpenAI

from config import settings
from config.settings import SPACY_MODEL


class EntityExtractor:
    def __init__(self, groq_api_key=None, groq_model="llama-3.1-8b-instant"):
        self.nlp = spacy.load(SPACY_MODEL)

        self.groq_model = groq_model
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        self.groq_client = None

        if self.groq_api_key:
            self.groq_client = OpenAI(
                api_key=self.groq_api_key,
                base_url=settings.GROQ_BASE_URL,
                timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
            )

        # Entity yang biasanya noise di paper
        self.stop_entities = {
            "et al", "et al.", "al.", "fig", "figure", "table",
            "section", "sec.", "appendix", "eq.", "equation"
        }

        # Label yang umumnya masih berguna di paper
        self.allowed_labels = {
            "ORG", "PERSON", "GPE", "LOC", "PRODUCT",
            "EVENT", "WORK_OF_ART", "LAW", "LANGUAGE",
            "DATE", "NORP", "FAC"
        }

    # ========================================================
    # CLEAN ENTITY TEXT
    # Bersihkan entity mentah dari spaCy
    # ========================================================
    def clean_entity_text(self, text: str) -> str:
        text = text.strip()
        text = re.sub(r"\s+", " ", text)
        text = text.strip(" ,.;:()[]{}")
        return text

    # ========================================================
    # CHECK VALID ENTITY
    # Filter entity noise
    # ========================================================
    def is_valid_entity(self, ent_text: str, ent_label: str) -> bool:
        text_lower = ent_text.lower().strip()

        if not ent_text:
            return False
        if len(ent_text) <= 2:
            return False
        if text_lower in self.stop_entities:
            return False
        if re.fullmatch(r"(19|20)\d{2}", ent_text):
            return False
        if ent_text.isdigit():
            return False
        if re.fullmatch(r"[\W_]+", ent_text):
            return False
        if ent_label not in self.allowed_labels:
            return False

        return True

    # ========================================================
    # EXTRACT ENTITIES
    # Input : retrieved chunks
    # Output: entity_map + all_entities
    # ========================================================
    def extract_entities(self, chunks):
        entity_map = defaultdict(list)
        all_entities = []

        for chunk in chunks:
            doc = self.nlp(chunk["text"])
            chunk_entities = []
            seen_in_chunk = set()

            for ent in doc.ents:
                ent_text = self.clean_entity_text(ent.text)
                ent_label = ent.label_

                if not self.is_valid_entity(ent_text, ent_label):
                    continue

                key = (ent_text.lower(), ent_label)
                if key in seen_in_chunk:
                    continue

                seen_in_chunk.add(key)
                chunk_entities.append((ent_text, ent_label))

                all_entities.append({
                    "chunk_id": chunk["chunk_id"],
                    "text": ent_text,
                    "label": ent_label
                })

            entity_map[chunk["chunk_id"]] = chunk_entities

        return entity_map, all_entities

    def _should_use_llm(self, chunk_text, entities):
        if self.groq_client is None:
            return False
        if len(entities) < 2:
            return False
        if len(chunk_text.strip()) < 80:
            return False
        return True

    def _build_relation_prompt(self, chunk_text, entities):
        entity_lines = []
        for ent_text, ent_label in entities[:20]:
            entity_lines.append(f'- {ent_text} ({ent_label})')
        entity_block = "\n".join(entity_lines) if entity_lines else "- none"

        return f"""
You are an information extraction assistant.
Extract only high-confidence relations that are explicitly supported by the text.
Return valid JSON only.

Schema:
{{
  "relations": [
    {{
      "head": "entity 1",
      "relation": "short_relation_label",
      "tail": "entity 2"
    }}
  ]
}}

Rules:
- Use only entities from the candidate list when possible.
- Keep relation labels short, snake_case if possible.
- Do not invent facts.
- If no clear relation exists, return {{"relations": []}}.
- Maximum 8 relations.

Candidate entities:
{entity_block}

Text:
{chunk_text}
""".strip()

    def _call_groq_relations(self, prompt, max_retries=5):
        if self.groq_client is None:
            return []

        last_error = None

        for attempt in range(max_retries):
            try:
                response = self.groq_client.chat.completions.create(
                    model=self.groq_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You extract relations as strict JSON."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0,
                    max_completion_tokens=300,
                    response_format={"type": "json_object"}
                )

                content = response.choices[0].message.content
                data = json.loads(content)
                relations = data.get("relations", [])

                cleaned_relations = []
                seen = set()
                for rel in relations:
                    head = self.clean_entity_text(str(rel.get("head", "")))
                    relation = str(rel.get("relation", "")).strip().lower()
                    tail = self.clean_entity_text(str(rel.get("tail", "")))

                    if not head or not relation or not tail:
                        continue
                    if head.lower() == tail.lower():
                        continue

                    key = (head.lower(), relation, tail.lower())
                    if key in seen:
                        continue
                    seen.add(key)

                    cleaned_relations.append({
                        "head": head,
                        "relation": relation,
                        "tail": tail,
                        "source": "groq"
                    })

                return cleaned_relations

            except Exception as e:
                last_error = e
                error_text = str(e).lower()

                if "429" in error_text or "rate" in error_text or "limit" in error_text:
                    sleep_seconds = min(2 ** attempt, 20)
                    time.sleep(sleep_seconds)
                    continue

                if attempt < max_retries - 1:
                    time.sleep(1.5)
                    continue

        print(f"[EntityExtractor] Groq relation extraction failed: {last_error}")
        return []

    # ========================================================
    # EXTRACT RELATIONS
    # Prioritas: Groq LLM -> fallback rule-based co-occurrence
    # ========================================================
    def extract_relations_llm(self, chunk_text, entities, llm_client=None):
        if len(entities) < 2:
            return []

        if llm_client is not None:
            return llm_client.extract_relations(chunk_text, entities)

        if self._should_use_llm(chunk_text, entities):
            prompt = self._build_relation_prompt(chunk_text, entities)
            llm_relations = self._call_groq_relations(prompt)
            if llm_relations:
                return llm_relations

        entity_texts = [e[0] for e in entities]
        relations = []
        seen = set()

        for i in range(len(entity_texts)):
            for j in range(i + 1, len(entity_texts)):
                head = entity_texts[i]
                tail = entity_texts[j]
                key = (head.lower(), "co-occurs_with", tail.lower())

                if key in seen:
                    continue
                seen.add(key)

                relations.append({
                    "head": head,
                    "relation": "co-occurs_with",
                    "tail": tail,
                    "source": "rule-based"
                })

        return relations
