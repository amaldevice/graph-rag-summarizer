# ============================================================
# ENTITY EXTRACTOR
# Hybrid Entity Extraction: SpaCy NER + filtering + Groq relation mining
# ============================================================

from collections import defaultdict
import json
import logging
import math
import os
import re
import time

import spacy
from openai import OpenAI

from config import settings
from config.settings import SPACY_MODEL
from summarizer.provider_router import redact_provider_error


logger = logging.getLogger(__name__)


class EntityExtractor:
    def __init__(self, groq_api_key=None, groq_model="llama-3.1-8b-instant", provider_router=None):
        self.nlp = spacy.load(SPACY_MODEL)

        self.groq_model = groq_model
        self.provider_router = provider_router
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        self.groq_client = None

        if self.groq_api_key:
            self.groq_client = OpenAI(
                api_key=self.groq_api_key,
                base_url=settings.GROQ_BASE_URL,
                timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
            )

        self._relation_extraction_llm_accepted = False
        self._relation_extraction_fallback_used = False

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

    @property
    def relation_extraction_mode(self):
        """Return the strongest relation-extraction path used for this instance."""
        if self._relation_extraction_llm_accepted:
            return "llm-enhanced"
        if self._relation_extraction_fallback_used:
            return "spacy-only"
        return "unavailable"

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
            chunk_key = chunk.get("chunk_uid", chunk["chunk_id"])
            if chunk.get("context_only"):
                entity_map[chunk_key] = []
                continue
            doc = self.nlp(chunk["text"])
            sentence_indexes = {}
            try:
                sentence_indexes = {
                    (sentence.start_char, sentence.end_char): index
                    for index, sentence in enumerate(doc.sents)
                }
            except (AttributeError, TypeError, ValueError):
                pass
            chunk_entities = []
            seen_in_chunk = set()

            for ent in doc.ents:
                ent_text = self.clean_entity_text(ent.text)
                ent_label = ent.label_

                if not self.is_valid_entity(ent_text, ent_label):
                    continue

                entity_record = {
                    "chunk_id": chunk["chunk_id"],
                    "chunk_uid": chunk_key,
                    "text": ent_text,
                    "label": ent_label
                }
                for field in ("start_char", "end_char"):
                    value = getattr(ent, field, None)
                    if isinstance(value, int):
                        entity_record[field] = value
                try:
                    sentence = ent.sent
                except (AttributeError, TypeError, ValueError):
                    sentence = None
                if sentence is not None:
                    sentence_start = getattr(sentence, "start_char", None)
                    sentence_end = getattr(sentence, "end_char", None)
                    if isinstance(sentence_start, int) and isinstance(sentence_end, int):
                        entity_record["sentence_start_char"] = sentence_start
                        entity_record["sentence_end_char"] = sentence_end
                        sentence_index = sentence_indexes.get((sentence_start, sentence_end))
                        if sentence_index is not None:
                            entity_record["sentence_index"] = sentence_index
                all_entities.append(entity_record)

                key = (ent_text.lower(), ent_label)
                if key in seen_in_chunk:
                    continue

                seen_in_chunk.add(key)
                chunk_entities.append((ent_text, ent_label))

            entity_map[chunk_key] = chunk_entities

        return entity_map, all_entities

    def _should_use_llm(self, chunk_text, entities):
        if not self._has_available_relation_provider():
            return False
        if len(entities) < 2:
            return False
        if len(chunk_text.strip()) < 80:
            return False
        return True

    def _has_available_relation_provider(self):
        if self.provider_router is not None:
            has_available_provider = getattr(self.provider_router, "has_available_provider", None)
            if callable(has_available_provider):
                try:
                    return bool(has_available_provider())
                except (KeyError, TypeError, ValueError, RuntimeError) as exc:
                    logger.warning("Relation provider is unavailable; using spaCy-only fallback: %s", exc)
                    return False

            resolve_chain = getattr(self.provider_router, "resolve_chain", None)
            if not callable(resolve_chain):
                return True
            try:
                return bool(resolve_chain())
            except (KeyError, TypeError, ValueError, RuntimeError) as exc:
                logger.warning("Relation provider is unavailable; using spaCy-only fallback: %s", exc)
                return False
        return self.groq_client is not None

    def _parse_relation_response(self, content, source, *, include_confidence=False):
        try:
            payload = json.loads(content)
        except (TypeError, json.JSONDecodeError) as exc:
            logger.warning("Skipping malformed LLM relation response: %s", exc)
            return []

        if not isinstance(payload, dict):
            logger.warning("Skipping malformed LLM relation response: expected an object")
            return []
        records = payload.get("relations", [])
        return self._validate_relation_records(records, source, include_confidence=include_confidence)

    def _validate_relation_records(self, records, source, *, include_confidence=False):
        if not isinstance(records, list):
            logger.warning("Skipping malformed LLM relation response: 'relations' must be a list")
            return []

        relations = []
        seen = set()
        for record in records:
            relation = self._validate_relation_record(record, source, include_confidence=include_confidence)
            if relation is None:
                continue
            key = (relation["head"].lower(), relation["relation"], relation["tail"].lower())
            if key in seen:
                continue
            seen.add(key)
            relations.append(relation)
        return relations

    def _validate_relation_record(self, record, source, *, include_confidence=False):
        if not isinstance(record, dict):
            logger.warning("Skipping malformed LLM relation: expected an object")
            return None

        head = record.get("head")
        relation = record.get("relation")
        tail = record.get("tail")
        if not all(isinstance(value, str) for value in (head, relation, tail)):
            logger.warning("Skipping malformed LLM relation: head, relation, and tail must be strings")
            return None

        head = self.clean_entity_text(head)
        relation = relation.strip().lower()
        tail = self.clean_entity_text(tail)
        if not head or not relation or not tail or head.lower() == tail.lower():
            logger.warning("Skipping malformed LLM relation: fields must be non-empty and distinct")
            return None

        cleaned = {
            "head": head,
            "relation": relation,
            "tail": tail,
            "source": source,
        }
        if include_confidence:
            try:
                confidence = float(record.get("confidence", 1.0))
            except (TypeError, ValueError):
                logger.warning("Skipping malformed LLM relation: confidence must be numeric")
                return None
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                logger.warning("Skipping malformed LLM relation: confidence must be between 0 and 1")
                return None
            cleaned.update({"confidence": confidence, "status": "accepted"})
        return cleaned

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
                return self._parse_relation_response(content, "groq")

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

        print(f"[EntityExtractor] Groq relation extraction failed: {redact_provider_error(last_error)}")
        return []

    def _call_provider_relations(self, prompt):
        if self.provider_router is None:
            return []
        try:
            content = self.provider_router.call_llm(
                "You extract relations as strict JSON.",
                prompt,
            )
            source = getattr(self.provider_router, "active_provider", None) or "provider-router"
            return self._parse_relation_response(content, source, include_confidence=True)
        except Exception as exc:
            logger.warning(
                "Relation provider call failed; using spaCy-only fallback: %s",
                redact_provider_error(exc),
            )
            return []

    # ========================================================
    # EXTRACT RELATIONS
    # Prioritas: Groq LLM -> fallback rule-based co-occurrence
    # ========================================================
    def extract_relations_llm(self, chunk_text, entities, llm_client=None):
        if len(entities) < 2:
            return []

        if llm_client is not None:
            llm_relations = self._validate_relation_records(
                llm_client.extract_relations(chunk_text, entities),
                "llm-client",
                include_confidence=True,
            )
            if llm_relations:
                self._relation_extraction_llm_accepted = True
                return llm_relations

        elif self._should_use_llm(chunk_text, entities):
            prompt = self._build_relation_prompt(chunk_text, entities)
            llm_relations = (
                self._call_provider_relations(prompt)
                if self.provider_router is not None
                else self._call_groq_relations(prompt)
            )
            if llm_relations:
                self._relation_extraction_llm_accepted = True
                return llm_relations

        self._relation_extraction_fallback_used = True
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
