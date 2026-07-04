# ============================================================
# FEEDBACK LOOP CONTROLLER
# Decide adaptive next steps after quality evaluation
# ============================================================

import json
from pathlib import Path
from typing import Dict, Optional


class FeedbackLoopController:
    def __init__(self, max_retries: int = 2):
        self.max_retries = max_retries

    def decide(
        self,
        quality_result: Dict,
        action_result: Dict,
        retry_state: Optional[Dict] = None
    ) -> Dict:
        retry_state = retry_state or {
            "retrieval_retries": 0,
            "prompt_retries": 0,
            "reduce_retries": 0,
            "total_retries": 0
        }

        status = quality_result.get("status", "FAIL")
        action = action_result.get("action", "manual_review")

        if status == "PASS":
            return {
                "stop": True,
                "final_decision": "accept",
                "next_stage": None,
                "updated_retry_state": retry_state,
                "message": "Quality gate passed; no retry needed."
            }

        if retry_state.get("total_retries", 0) >= self.max_retries:
            return {
                "stop": True,
                "final_decision": "manual_review",
                "next_stage": None,
                "updated_retry_state": retry_state,
                "message": "Maximum retry budget reached; escalate to manual review."
            }

        updated = dict(retry_state)
        updated["total_retries"] = updated.get("total_retries", 0) + 1

        if action == "review":
            return {
                "stop": True,
                "final_decision": "review",
                "next_stage": None,
                "updated_retry_state": updated,
                "message": "Quality gate returned WARN; route to human review or optional refinement."
            }

        if action == "retry_retrieval":
            updated["retrieval_retries"] = updated.get("retrieval_retries", 0) + 1
            return {
                "stop": False,
                "final_decision": None,
                "next_stage": "retrieval",
                "updated_retry_state": updated,
                "message": "Retry retrieval with broader or adjusted context, then rebuild graph and summaries."
            }

        if action == "retry_prompt_or_reduce":
            prompt_retries = updated.get("prompt_retries", 0)
            reduce_retries = updated.get("reduce_retries", 0)

            if prompt_retries <= reduce_retries:
                updated["prompt_retries"] = prompt_retries + 1
                return {
                    "stop": False,
                    "final_decision": None,
                    "next_stage": "prompt",
                    "updated_retry_state": updated,
                    "message": "Retry prompt construction or map summarization with stricter instructions."
                }

            updated["reduce_retries"] = reduce_retries + 1
            return {
                "stop": False,
                "final_decision": None,
                "next_stage": "reduce",
                "updated_retry_state": updated,
                "message": "Retry hierarchical reduction with refined merge instructions."
            }

        return {
            "stop": True,
            "final_decision": "manual_review",
            "next_stage": None,
            "updated_retry_state": updated,
            "message": "Fallback to manual review because no automatic retry strategy matched."
        }

    def save_decision(self, decision_result: Dict, output_path="output/feedback_loop_decision.json"):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with open(out, "w", encoding="utf-8") as f:
            json.dump(decision_result, f, indent=2, ensure_ascii=False)

        print(f"✅ Feedback loop decision saved: {out}")
        return str(out)
