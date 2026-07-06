# ============================================================
# QUALITY CHECKER
# Pass / Warn / Fail gate for generated summary quality
# ============================================================

import json
from pathlib import Path
from typing import Dict, List


class QualityChecker:
    def __init__(
        self,
        min_rougeL: float = 0.15,
        min_bertscore_f1: float = 0.80,
        min_lexical_overlap: float = 0.30,
        min_summary_words: int = 40,
        max_summary_words: int = 400
    ):
        self.min_rougeL = min_rougeL
        self.min_bertscore_f1 = min_bertscore_f1
        self.min_lexical_overlap = min_lexical_overlap
        self.min_summary_words = min_summary_words
        self.max_summary_words = max_summary_words

    def check(self, evaluation_result: Dict) -> Dict:
        status = "PASS"
        issues: List[str] = []
        warnings: List[str] = []
        metric_decisions = {}

        generated_length = evaluation_result.get("generated_length", 0)
        if generated_length < self.min_summary_words:
            status = "WARN" if status == "PASS" else status
            warnings.append(
                f"Generated summary may be too short: {generated_length} words < {self.min_summary_words}"
            )

        if generated_length > self.max_summary_words:
            status = "WARN" if status == "PASS" else status
            warnings.append(
                f"Generated summary may be too long: {generated_length} words > {self.max_summary_words}"
            )

        if evaluation_result.get("has_reference"):
            rouge = evaluation_result.get("rouge") or {}
            bertscore = evaluation_result.get("bertscore") or {}

            rougeL = rouge.get("rougeL_fmeasure")
            bert_f1 = bertscore.get("f1")

            if rougeL is not None and rougeL < self.min_rougeL:
                status = "FAIL"
                issues.append(
                    f"ROUGE-L below threshold: {rougeL:.4f} < {self.min_rougeL:.4f}"
                )

            if bert_f1 is not None and bert_f1 < self.min_bertscore_f1:
                status = "FAIL"
                issues.append(
                    f"BERTScore F1 below threshold: {bert_f1:.4f} < {self.min_bertscore_f1:.4f}"
                )

            if evaluation_result.get("rouge") is None:
                warnings.append("ROUGE unavailable; rouge-score package not installed")
            if evaluation_result.get("bertscore") is None:
                warnings.append("BERTScore unavailable; bert-score package not installed")

        else:
            lexical_overlap = evaluation_result.get("lexical_overlap")
            if lexical_overlap is not None and lexical_overlap < self.min_lexical_overlap:
                status = "FAIL"
                issues.append(
                    f"Lexical overlap below threshold: {lexical_overlap:.4f} < {self.min_lexical_overlap:.4f}"
                )

        for name, metric in (evaluation_result.get("grounded_metrics") or {}).items():
            metric_status = metric.get("status", "unavailable")
            score = metric.get("score")
            decision = "unavailable"
            if metric_status == "available":
                decision = "pass"
                if score is not None and score < self.min_lexical_overlap:
                    decision = "fail"
                    status = "FAIL"
                    issues.append(f"{name} below threshold: {score:.4f} < {self.min_lexical_overlap:.4f}")
            else:
                warnings.append(f"{name} unavailable: {metric.get('reason', 'not configured')}")
            metric_decisions[name] = {
                "status": metric_status,
                "score": score,
                "decision": decision,
                "reason": metric.get("reason", ""),
            }

        if not issues and not warnings:
            message = "Quality gate passed"
        elif not issues and warnings:
            message = "Quality gate passed with warnings"
        else:
            message = "Quality gate failed"

        return {
            "status": status,
            "passed": status != "FAIL",
            "message": message,
            "issues": issues,
            "warnings": warnings,
            "metric_decisions": metric_decisions,
            "thresholds": {
                "min_rougeL": self.min_rougeL,
                "min_bertscore_f1": self.min_bertscore_f1,
                "min_lexical_overlap": self.min_lexical_overlap,
                "min_summary_words": self.min_summary_words,
                "max_summary_words": self.max_summary_words
            }
        }

    def suggest_action(self, quality_result: Dict) -> Dict:
        status = quality_result.get("status", "FAIL")

        if status == "PASS":
            return {
                "action": "accept",
                "reason": "Summary passed the current quality gate"
            }

        if status == "WARN":
            return {
                "action": "review",
                "reason": "Summary is acceptable but should be reviewed or refined"
            }

        issues = " ".join(quality_result.get("issues", []))
        if "qa_coverage" in issues or "Lexical overlap" in issues:
            return {
                "action": "retry_retrieval",
                "reason": "Summary may not be grounded strongly enough in source chunks"
            }
        if "geval" in issues or "factcc" in issues or "summac" in issues:
            return {
                "action": "retry_prompt",
                "reason": "Grounded quality signal failed; retry prompt and map summarization"
            }
        if "ROUGE-L" in issues or "BERTScore" in issues:
            return {
                "action": "retry_reduce",
                "reason": "Summary content quality is below threshold against reference"
            }

        return {
            "action": "manual_review",
            "reason": "Quality gate failed for an unspecified reason"
        }

    def save_quality_report(self, quality_result: Dict, action_result: Dict, output_path="output/quality_gate_report.json"):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        report = {
            "quality_result": quality_result,
            "suggested_action": action_result
        }

        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"✅ Quality gate report saved: {out}")
        return str(out)
