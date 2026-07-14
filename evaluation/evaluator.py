# ============================================================
# EVALUATOR
# Lightweight evaluation layer for generated summaries
# ============================================================

import json
import re
from pathlib import Path
from typing import Dict, List, Optional


_MONTH_NAMES = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)"
)
_DATE_PATTERN = re.compile(
    rf"\b(?:{_MONTH_NAMES})\.?\s+\d{{1,2}}(?:,\s*|\s+)\d{{4}}\b"
    rf"|\b\d{{1,2}}\s+(?:{_MONTH_NAMES})\.?\s+\d{{4}}\b"
    rf"|\b(?:{_MONTH_NAMES})\.?\s+\d{{4}}\b"
    rf"|\b(?:\d{{4}}[-/]\d{{1,2}}[-/]\d{{1,2}}|\d{{1,2}}[-/]\d{{1,2}}[-/]\d{{4}})\b",
    re.IGNORECASE,
)
_MONTH_TOKEN_PATTERN = re.compile(rf"\b(?:{_MONTH_NAMES})\.?", re.IGNORECASE)
_NUMBER_PATTERN = re.compile(r"(?<![\w.\d])[+-]?\d[\d,]*(?:\.\d+)?%?(?!\w)")
_NON_ENTITY_TITLE_WORDS = {
    "a", "additionally", "although", "an", "and", "because", "but", "consequently",
    "dec", "december", "feb", "february", "finally", "first", "for", "from",
    "furthermore", "he", "however", "i", "in", "it", "jan", "january", "jul", "july",
    "jun", "june", "mar", "march", "may", "meanwhile", "moreover", "nov", "november",
    "oct", "october", "of", "on", "or", "overall", "second", "sep", "sept", "september",
    "she", "that", "the", "their", "therefore", "these", "they", "third", "this", "those",
    "to", "we", "while", "with", "you",
}

try:
    from rouge_score import rouge_scorer
except ImportError:
    rouge_scorer = None

try:
    from bert_score import score as bertscore_score
except ImportError:
    bertscore_score = None


class SummaryEvaluator:
    def __init__(self, use_stemmer: bool = True, bert_lang: str = "en", judge_session=None):
        self.use_stemmer = use_stemmer
        self.bert_lang = bert_lang
        self.judge_session = judge_session

    def evaluate_with_reference(self, generated_summary: str, reference_summary: str) -> Dict:
        result = {
            "has_reference": True,
            "generated_length": len(generated_summary.split()),
            "reference_length": len(reference_summary.split())
        }

        if rouge_scorer is not None:
            scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=self.use_stemmer)
            rouge_scores = scorer.score(reference_summary, generated_summary)
            result["rouge"] = {
                "rouge1_fmeasure": float(rouge_scores["rouge1"].fmeasure),
                "rouge2_fmeasure": float(rouge_scores["rouge2"].fmeasure),
                "rougeL_fmeasure": float(rouge_scores["rougeL"].fmeasure)
            }
        else:
            result["rouge"] = None
            result["rouge_warning"] = "rouge-score package is not installed"

        if bertscore_score is not None:
            p, r, f1 = bertscore_score(
                [generated_summary],
                [reference_summary],
                lang=self.bert_lang,
                verbose=False
            )
            result["bertscore"] = {
                "precision": float(p[0].item()),
                "recall": float(r[0].item()),
                "f1": float(f1[0].item())
            }
        else:
            result["bertscore"] = None
            result["bertscore_warning"] = "bert-score package is not installed"

        return result

    def evaluate_without_reference(
        self,
        generated_summary: str,
        source_chunks: Optional[List[Dict]] = None,
        query: Optional[str] = None,
    ) -> Dict:
        source_text = " ".join(chunk.get("text", "") for chunk in (source_chunks or []))
        source_words = source_text.split()
        summary_words = generated_summary.split()

        source_vocab = set(w.lower().strip(".,;:!?()[]{}\"'") for w in source_words if w.strip())
        summary_vocab = set(w.lower().strip(".,;:!?()[]{}\"'") for w in summary_words if w.strip())

        lexical_overlap = 0.0
        if summary_vocab:
            lexical_overlap = len(summary_vocab.intersection(source_vocab)) / max(len(summary_vocab), 1)

        result = {
            "has_reference": False,
            "generated_length": len(summary_words),
            "source_length": len(source_words),
            "lexical_overlap": lexical_overlap,
            "source_chunk_count": len(source_chunks or []),
        }
        result["grounded_metrics"] = self._grounded_metrics(
            generated_summary=generated_summary,
            source_text=source_text,
            source_chunks=source_chunks or [],
            query=query,
        )
        return result

    def _grounded_metrics(
        self,
        generated_summary: str,
        source_text: str,
        source_chunks: List[Dict],
        query: Optional[str],
    ) -> Dict:
        # ponytail: FactCC/SummaC are optional research evaluators; report absence instead of adding heavy deps.
        metrics = {
            "factcc": {
                "status": "unavailable",
                "score": None,
                "reason": "FactCC evaluator is not configured",
            },
            "summac": {
                "status": "unavailable",
                "score": None,
                "reason": "SummaC evaluator is not configured",
            },
            "geval": {
                "status": "unavailable",
                "score": None,
                "reason": "LLM judge session is not configured",
            },
            "qa_coverage": self._qa_coverage(generated_summary, source_text, query),
        }
        sentence_support, supports = self._sentence_support(generated_summary, source_chunks)
        metrics.update({
            "entity_consistency": self._entity_consistency(generated_summary, source_text),
            "number_date_consistency": self._number_date_consistency(generated_summary, source_text),
            "sentence_support": sentence_support,
            "citation_coverage": self._citation_coverage(supports, source_chunks),
            "redundancy": self._redundancy(generated_summary),
            "query_relevance": self._query_relevance(generated_summary, query),
            "evidence_diversity": self._evidence_diversity(source_chunks),
        })
        if self.judge_session is not None:
            metrics["geval"] = self._geval(generated_summary, source_text, query)
        return metrics

    @staticmethod
    def _metric(score: float, reason: str, **details) -> Dict:
        result = {"status": "available", "score": score, "reason": reason}
        if details:
            result["details"] = details
        return result

    @staticmethod
    def _unavailable(reason: str) -> Dict:
        return {"status": "unavailable", "score": None, "reason": reason}

    @staticmethod
    def _words(text: str) -> set[str]:
        return set(re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*", text.lower()))

    @staticmethod
    def _sentences(text: str) -> List[str]:
        return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]

    @staticmethod
    def _chunk_id(chunk: Dict):
        return chunk.get("chunk_uid") or chunk.get("chunk_id")

    @staticmethod
    def _entities(text: str) -> set[str]:
        entities = set()
        for match in re.finditer(r"\b[A-Z]{2,}\b|\b[A-Z][a-z]+\b", text):
            value = match.group()
            if value.casefold() in _NON_ENTITY_TITLE_WORDS:
                continue
            if not value.isupper() and text[match.end():].lstrip().startswith(","):
                continue
            entities.add(value.casefold())
        return entities

    @staticmethod
    def _numbers_and_dates(text: str) -> set[str]:
        date_matches = list(_DATE_PATTERN.finditer(text))
        values = {
            SummaryEvaluator._normalize_date(match.group())
            for match in date_matches
        }
        for match in _NUMBER_PATTERN.finditer(text):
            if not any(match.start() < date.end() and match.end() > date.start() for date in date_matches):
                values.add(match.group().replace(",", ""))
        return values

    @staticmethod
    def _normalize_date(value: str) -> str:
        value = re.sub(r"\s+", " ", value).replace(",", "").casefold()
        if re.fullmatch(r"\d+[-/]\d+[-/]\d+", value):
            return "-".join(str(int(part)) for part in re.split(r"[-/]", value))
        return _MONTH_TOKEN_PATTERN.sub(
            lambda month: month.group().rstrip(".")[:3].casefold(),
            value,
        )

    def _entity_consistency(self, generated_summary: str, source_text: str) -> Dict:
        summary_entities = self._entities(generated_summary)
        if not summary_entities:
            return self._metric(1.0, "No named-like entities in summary")
        source_entities = self._entities(source_text)
        score = len(summary_entities & source_entities) / len(summary_entities)
        return self._metric(score, "Named-like summary entities found in source")

    def _number_date_consistency(self, generated_summary: str, source_text: str) -> Dict:
        summary_values = self._numbers_and_dates(generated_summary)
        if not summary_values:
            return self._metric(1.0, "No numbers or dates in summary")
        source_values = self._numbers_and_dates(source_text)
        score = len(summary_values & source_values) / len(summary_values)
        return self._metric(score, "Summary numbers and dates found in source")

    def _sentence_support(self, generated_summary: str, source_chunks: List[Dict]):
        sentences = self._sentences(generated_summary)
        if not sentences:
            return self._unavailable("Summary contains no sentences"), []
        if not source_chunks:
            return self._unavailable("No source chunks available"), []

        source_vocabularies = [self._words(chunk.get("text", "")) for chunk in source_chunks]
        supports = []
        for sentence_index, sentence in enumerate(sentences):
            sentence_words = self._words(sentence)
            scores = [
                len(sentence_words & source_words) / len(sentence_words) if sentence_words else 0.0
                for source_words in source_vocabularies
            ]
            index = max(range(len(scores)), key=scores.__getitem__)
            supports.append({
                "sentence_index": sentence_index,
                "sentence": sentence,
                "chunk_index": index,
                "score": scores[index],
            })

        score = sum(item["score"] >= 0.5 for item in supports) / len(supports)
        return self._metric(score, "Best lexical support per summary sentence"), supports

    def _citation_coverage(self, supports: List[Dict], source_chunks: List[Dict]) -> Dict:
        if not supports:
            return self._unavailable("No sentence support available")
        sentence_support = []
        for item in supports:
            chunk_id = self._chunk_id(source_chunks[item["chunk_index"]])
            if item["score"] >= 0.5 and chunk_id is not None:
                sentence_support.append({
                    "sentence_index": item["sentence_index"],
                    "sentence": item["sentence"],
                    "chunk_id": str(chunk_id),
                    "support_score": item["score"],
                })
        if not sentence_support:
            return self._unavailable("No supported summary sentences have stable chunk IDs")
        chunk_ids = list(dict.fromkeys(item["chunk_id"] for item in sentence_support))
        return self._metric(
            len(sentence_support) / len(supports),
            "Summary sentences trace to lexical source support",
            supporting_chunk_ids=chunk_ids,
            sentence_support=sentence_support,
        )

    def _redundancy(self, generated_summary: str) -> Dict:
        sentences = [self._words(sentence) for sentence in self._sentences(generated_summary)]
        if len(sentences) < 2:
            return self._metric(1.0, "Fewer than two summary sentences")
        overlap = max(
            len(left & right) / len(left | right) if left | right else 0.0
            for index, left in enumerate(sentences)
            for right in sentences[index + 1:]
        )
        return self._metric(1.0 - overlap, "Lower score indicates repeated summary sentences")

    def _query_relevance(self, generated_summary: str, query: Optional[str]) -> Dict:
        if not query:
            return self._unavailable("No query available")
        query_words = self._words(query)
        if not query_words:
            return self._unavailable("Query contains no comparable terms")
        score = len(self._words(generated_summary) & query_words) / len(query_words)
        return self._metric(score, "Query terms represented in summary")

    def _evidence_diversity(self, source_chunks: List[Dict]) -> Dict:
        if not source_chunks:
            return self._unavailable("No selected source chunks available")
        groups = []
        for chunk in source_chunks:
            hierarchy = chunk.get("hierarchy") or {}
            layout = chunk.get("layout") or {}
            group = next(
                (
                    value
                    for value in (
                        chunk.get("community"),
                        hierarchy.get("section_id"),
                        layout.get("page_no"),
                        chunk.get("page"),
                    )
                    if value is not None
                ),
                None,
            )
            if group is not None:
                groups.append(str(group))
        if not groups:
            return self._unavailable("Selected chunks have no community, section, or page metadata")
        if len(source_chunks) == 1:
            return self._metric(1.0, "Single selected evidence chunk is genuinely narrow")
        return self._metric(
            len(set(groups)) / len(source_chunks),
            "Distinct evidence groups among selected source chunks",
        )

    def _qa_coverage(self, generated_summary: str, source_text: str, query: Optional[str]) -> Dict:
        summary_vocab = self._vocab(generated_summary)
        if query:
            targets = self._vocab(query)
        else:
            targets = set(list(self._vocab(source_text))[:20])
        score = 1.0 if not targets else len(summary_vocab.intersection(targets)) / max(len(targets), 1)
        return {
            "status": "available",
            "score": score,
            "reason": "Query term coverage proxy",
        }

    def _geval(self, generated_summary: str, source_text: str, query: Optional[str]) -> Dict:
        prompt = (
            "Score this summary from 0 to 1 for faithfulness to the source. "
            f"Query: {query or ''}\nSource: {source_text[:3000]}\nSummary: {generated_summary}"
        )
        try:
            raw = self.judge_session.call_llm("Return only a number from 0 to 1.", prompt)
            score = float(str(raw).strip().split()[0])
            score = max(0.0, min(1.0, score))
            return {"status": "available", "score": score, "reason": "LLM judge score"}
        except Exception as exc:
            return {"status": "unavailable", "score": None, "reason": str(exc)}

    def _vocab(self, text: str) -> set:
        words = []
        for word in text.split():
            cleaned = word.lower().strip(".,;:!?()[]{}\"'")
            if cleaned:
                words.append(cleaned)
        return set(words)

    def build_quality_decision(
        self,
        evaluation_result: Dict,
        min_rougeL: float = 0.15,
        min_bertscore_f1: float = 0.80,
        min_lexical_overlap: float = 0.30
    ) -> Dict:
        passed = True
        reasons = []

        if evaluation_result.get("has_reference"):
            rouge = evaluation_result.get("rouge") or {}
            bertscore = evaluation_result.get("bertscore") or {}

            rougeL = rouge.get("rougeL_fmeasure")
            bert_f1 = bertscore.get("f1")

            if rougeL is not None and rougeL < min_rougeL:
                passed = False
                reasons.append(f"ROUGE-L below threshold: {rougeL:.4f} < {min_rougeL:.4f}")

            if bert_f1 is not None and bert_f1 < min_bertscore_f1:
                passed = False
                reasons.append(f"BERTScore F1 below threshold: {bert_f1:.4f} < {min_bertscore_f1:.4f}")
        else:
            lexical_overlap = evaluation_result.get("lexical_overlap")
            if lexical_overlap is not None and lexical_overlap < min_lexical_overlap:
                passed = False
                reasons.append(
                    f"Lexical overlap below threshold: {lexical_overlap:.4f} < {min_lexical_overlap:.4f}"
                )

        if not reasons:
            reasons.append("Quality check passed")

        return {
            "passed": passed,
            "reasons": reasons
        }

    def save_evaluation_json(self, evaluation_result: Dict, output_path="output/evaluation_result.json"):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with open(out, "w", encoding="utf-8") as f:
            json.dump(evaluation_result, f, indent=2, ensure_ascii=False)

        print(f"✅ Evaluation JSON saved: {out}")
        return str(out)

    def save_quality_json(self, quality_result: Dict, output_path="output/quality_check.json"):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with open(out, "w", encoding="utf-8") as f:
            json.dump(quality_result, f, indent=2, ensure_ascii=False)

        print(f"✅ Quality check JSON saved: {out}")
        return str(out)
