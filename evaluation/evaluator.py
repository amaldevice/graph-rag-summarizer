# ============================================================
# EVALUATOR
# Lightweight evaluation layer for generated summaries
# ============================================================

import json
from pathlib import Path
from typing import Dict, List, Optional

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
            query=query,
            lexical_overlap=lexical_overlap,
        )
        return result

    def _grounded_metrics(
        self,
        generated_summary: str,
        source_text: str,
        query: Optional[str],
        lexical_overlap: float,
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
        if self.judge_session is not None:
            metrics["geval"] = self._geval(generated_summary, source_text, query)
        return metrics

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
