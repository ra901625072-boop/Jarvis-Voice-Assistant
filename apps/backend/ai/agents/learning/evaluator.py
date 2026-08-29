import logging
from typing import Dict, Any

logger = logging.getLogger("JARVIS.LearningAgent.Evaluator")

class LearningEvaluator:
    @staticmethod
    def validate_recommendation(recommendation_type: str, payload: dict) -> bool:
        """
        Validates the recommendation payload structure.
        """
        if recommendation_type == "prompt_patch":
            required = ["agent_id", "recommended_patch"]
            return all(k in payload for k in required)
        elif recommendation_type == "regression_test":
            required = ["agent_id", "task_type", "goal"]
            return all(k in payload for k in required)
        elif recommendation_type == "routing_change":
            required = ["agent_id", "routing_action"]
            return all(k in payload for k in required)
        return True
