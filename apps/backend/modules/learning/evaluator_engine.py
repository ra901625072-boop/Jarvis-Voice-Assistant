"""
evaluator_engine.py
-------------------
Multi-Dimensional Evaluator for agent episodes and trajectories.
Evaluates:
- Quality (Goal completeness & correctness)
- Accuracy (Tool execution & verification)
- Efficiency (Duration & step optimality)
- Safety (Invariant compliance & security)
- Cost (Token & resource efficiency)
- Recovery (Error handling resilience)
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("JARVIS.EvaluatorEngine")


class EvaluatorEngine:
    """
    Evaluates completed execution episodes across multiple objective dimensions.
    """

    DEFAULT_WEIGHTS = {
        "quality": 0.30,
        "accuracy": 0.25,
        "efficiency": 0.15,
        "safety": 0.15,
        "cost": 0.05,
        "recovery": 0.10,
    }

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or self.DEFAULT_WEIGHTS

    def evaluate_episode(self, episode: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculates multi-dimensional scores for a given episode dictionary.
        """
        success = bool(episode.get("success", False))
        trajectory = episode.get("trajectory", [])
        duration_ms = float(episode.get("duration_ms", 0.0))
        tokens_used = int(episode.get("tokens_used", 0))
        error = episode.get("outcome", {}).get("error") or ""

        # 1. Quality Score (0.0 to 1.0)
        quality = 1.0 if success else 0.1
        if not success and "partial" in str(error).lower():
            quality = 0.4

        # 2. Accuracy Score (0.0 to 1.0)
        # Checks if tool calls had step errors
        step_errors = sum(1 for step in trajectory if step.get("error"))
        total_steps = max(1, len(trajectory))
        accuracy = max(0.0, 1.0 - (step_errors / total_steps)) if success else max(0.0, 0.6 - (step_errors / total_steps))

        # 3. Efficiency Score (0.0 to 1.0)
        # Penalizes excessive duration (> 60s) or excessive retry loops (> 10 steps for single subtask)
        time_penalty = min(1.0, duration_ms / 60000.0) * 0.4
        step_penalty = min(1.0, total_steps / 15.0) * 0.3
        efficiency = max(0.1, round(1.0 - time_penalty - step_penalty, 2))

        # 4. Safety Score (0.0 to 1.0)
        # Evaluates invariant compliance (e.g. no destructive force deletes or blocked resources)
        safety = 1.0
        err_lower = str(error).lower()
        if "permission_denied" in err_lower or "security_block" in err_lower:
            safety = 0.2
        elif "invariant" in err_lower:
            safety = 0.1

        # 5. Cost Score (0.0 to 1.0)
        # Token efficiency score
        if tokens_used <= 1000:
            cost_score = 1.0
        elif tokens_used <= 4000:
            cost_score = 0.8
        elif tokens_used <= 8000:
            cost_score = 0.6
        else:
            cost_score = 0.4

        # 6. Recovery Quality (0.0 to 1.0)
        # Did the agent encounter errors and recover?
        recovery_score = 1.0
        if step_errors > 0:
            if success:
                recovery_score = 0.95  # Successfully recovered from step errors
            else:
                recovery_score = 0.2  # Failed to recover

        # Compute overall compound utility
        utility = (
            self.weights["quality"] * quality
            + self.weights["accuracy"] * accuracy
            + self.weights["efficiency"] * efficiency
            + self.weights["safety"] * safety
            + self.weights["cost"] * cost_score
            + self.weights["recovery"] * recovery_score
        )
        utility = round(min(1.0, max(0.0, utility)), 4)

        evaluation_result = {
            "success": success,
            "quality": round(quality, 2),
            "accuracy": round(accuracy, 2),
            "efficiency": round(efficiency, 2),
            "safety": round(safety, 2),
            "cost": round(cost_score, 2),
            "recovery": round(recovery_score, 2),
            "overall_utility": utility,
        }

        return evaluation_result
