import os
from typing import Dict, Any, Optional

class LearningPolicy:
    @staticmethod
    def is_synthetic_test(goal_hint: str) -> bool:
        """
        Determines if the task outcome was part of a synthetic test or seed run.
        """
        if not goal_hint:
            return False
        return (
            os.environ.get("JARVIS_E2E_SIM") == "1" or
            goal_hint.startswith("seed_") or
            goal_hint.startswith("e2e_sim_")
        )

    @staticmethod
    def should_process_outcome(goal_hint: str) -> bool:
        """
        Determines if we should process a task based on environment setup and goal hint.
        """
        is_synthetic = LearningPolicy.is_synthetic_test(goal_hint)
        if is_synthetic and os.environ.get("JARVIS_ALLOW_SEED_WRITES") != "1":
            return False
        return True

    @staticmethod
    def evaluate_ema_threshold(ema: float) -> Optional[str]:
        """
        Returns a note or recommendation based on EMA score thresholds.
        """
        if ema >= 0.90:
            return "high_confidence"
        elif ema <= 0.60:
            return "critical_low_confidence"
        else:
            return "normal"

    @staticmethod
    def evaluate_recommendation_risk(data: Dict[str, Any]) -> str:
        """
        Classifies recommendation risk to determine auto-application safety.
        Returns: 'reject', 'review', or 'auto_apply'
        """
        # Parse potential confidence/completeness keys
        confidence = data.get("confidence", 1.0)
        if isinstance(confidence, (int, float)) and confidence < 0.70:
            return "review"

        completeness = data.get("completeness", 1.0)
        if isinstance(completeness, (int, float)) and completeness < 0.80:
            return "review"

        # Check for error classifications or warnings
        if data.get("severity") in ("warning", "critical"):
            return "review"

        # Check if the classification indicates manual inspection is needed
        if data.get("classification") in ("recurring_failure", "capability_change"):
            return "review"

        return "auto_apply"
