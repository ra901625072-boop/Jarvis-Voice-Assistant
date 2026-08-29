"""
apps/backend/ai/agents/research/memory/research_state.py
Research State Management, Audit Trail Tracking, and Checkpointing for Pause / Resume.
"""
import time
import json
import uuid
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict

from ai.agents.research.schemas.research import (
    ResearchObjective,
    ResearchPlan,
    ResearchBudget,
    ResearchDepth,
    ResearchMode,
)
from ai.agents.research.schemas.report import ResearchAuditTrail


@dataclass
class ResearchState:
    research_id: str = field(default_factory=lambda: f"res_{time.strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}")
    objective: Optional[ResearchObjective] = None
    status: str = "initialized"  # initialized, planning, searching, reflecting, synthesizing, completed, paused, failed
    plan: Optional[ResearchPlan] = None
    iteration: int = 0
    total_searches_conducted: int = 0
    total_sources_evaluated: int = 0
    total_evidence_extracted: int = 0
    total_claims_recorded: int = 0
    total_contradictions_found: int = 0
    unresolved_gaps: List[str] = field(default_factory=list)
    confidence_score: float = 0.0
    confidence_level: str = "LOW"
    start_time: float = field(default_factory=time.time)
    completed_time: Optional[float] = None
    error_message: Optional[str] = None
    final_report: Optional[str] = None
    audit_trail: ResearchAuditTrail = field(default_factory=ResearchAuditTrail)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "research_id": self.research_id,
            "objective": self.objective.to_dict() if self.objective else None,
            "status": self.status,
            "plan": self.plan.to_dict() if self.plan else None,
            "iteration": self.iteration,
            "total_searches_conducted": self.total_searches_conducted,
            "total_sources_evaluated": self.total_sources_evaluated,
            "total_evidence_extracted": self.total_evidence_extracted,
            "total_claims_recorded": self.total_claims_recorded,
            "total_contradictions_found": self.total_contradictions_found,
            "unresolved_gaps": self.unresolved_gaps,
            "confidence_score": self.confidence_score,
            "confidence_level": self.confidence_level,
            "start_time": self.start_time,
            "completed_time": self.completed_time,
            "error_message": self.error_message,
            "audit_trail": self.audit_trail.to_dict(),
        }

    def save_checkpoint(self, file_path: str) -> None:
        """Saves current research state to disk JSON for pause and resume."""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load_checkpoint(cls, file_path: str) -> "ResearchState":
        """Loads research state from disk JSON."""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        state = cls(
            research_id=data.get("research_id", ""),
            status=data.get("status", "initialized"),
            iteration=data.get("iteration", 0),
            total_searches_conducted=data.get("total_searches_conducted", 0),
            total_sources_evaluated=data.get("total_sources_evaluated", 0),
            total_evidence_extracted=data.get("total_evidence_extracted", 0),
            total_claims_recorded=data.get("total_claims_recorded", 0),
            total_contradictions_found=data.get("total_contradictions_found", 0),
            unresolved_gaps=data.get("unresolved_gaps", []),
            confidence_score=data.get("confidence_score", 0.0),
            confidence_level=data.get("confidence_level", "LOW"),
            start_time=data.get("start_time", time.time()),
            completed_time=data.get("completed_time"),
            error_message=data.get("error_message"),
        )
        return state
