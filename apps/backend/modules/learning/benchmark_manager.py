import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("JARVIS.BenchmarkManager")

class BenchmarkManager:
    def __init__(self, learning_orchestrator):
        self.orchestrator = learning_orchestrator

    def propose_regression_case(self, agent_id: str, task_type: str, goal: str, failure_pattern: str, error_summary: str, source_event_id: Optional[int] = None) -> int:
        payload = {
            "agent_id": agent_id,
            "task_type": task_type,
            "goal": goal,
            "failure_pattern": failure_pattern,
            "error_summary": error_summary
        }
        return self.orchestrator.create_recommendation(
            source_event_id=source_event_id,
            target_agent="verification_agent",
            recommendation_type="regression_test",
            payload=payload
        )

    def get_regression_cases(self) -> List[Dict[str, Any]]:
        recs = self.orchestrator.get_pending_recommendations()
        return [r for r in recs if r["recommendation_type"] == "regression_test"]
