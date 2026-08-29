from dataclasses import dataclass
from typing import List, Optional, Dict, Any

@dataclass
class OutcomeAnalysisSchema:
    classification: str  # "noise", "one_time_failure", "recurring_failure", "success_pattern", "capability_change"
    severity: str        # "info", "warning", "critical"
    pattern_key: Optional[str]
    summary: str

    @classmethod
    def validate(cls, data: dict) -> bool:
        required = ["classification", "severity", "summary"]
        return all(k in data for k in required)

@dataclass
class FailureReviewSchema:
    lesson: str
    importance: int

    @classmethod
    def validate(cls, data: dict) -> bool:
        return "lesson" in data and "importance" in data

@dataclass
class SuccessReviewSchema:
    goal: str
    plan_json: List[Dict[str, Any]]
    score: float

    @classmethod
    def validate(cls, data: dict) -> bool:
        return "goal" in data and "plan_json" in data

@dataclass
class PromptPatchSchema:
    agent_id: str
    recommended_patch: str
    reason: str

    @classmethod
    def validate(cls, data: dict) -> bool:
        return "agent_id" in data and "recommended_patch" in data

@dataclass
class LearningCycleSummarySchema:
    summary: str
    insights: List[Dict[str, Any]]
    actions: List[Dict[str, Any]]

    @classmethod
    def validate(cls, data: dict) -> bool:
        return "summary" in data and "insights" in data and "actions" in data
