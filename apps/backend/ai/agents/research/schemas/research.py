"""
apps/backend/ai/agents/research/schemas/research.py
Pydantic and dataclass models for Research Objectives, Plan, SubQuestions, Depth, and Budget.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional
import time


class ResearchDepth(str, Enum):
    QUICK = "quick"              # 500–1,000 words, 5–10 sources, 1 iteration
    NORMAL = "normal"            # 1,500–3,000 words, 10–20 sources, 2–3 iterations
    DEEP = "deep"                # 4,000–8,000 words, 20–40 sources, 3–6 iterations
    COMPREHENSIVE = "comprehensive"  # 8,000–15,000+ words, 40–80+ sources, 5–10 iterations


class ResearchMode(str, Enum):
    GENERAL = "general"
    MARKET_BUSINESS = "market_business"
    COMPETITOR_ANALYSIS = "competitor_analysis"
    ACADEMIC_SCIENTIFIC = "academic_scientific"
    TECHNICAL_ARCHITECTURE = "technical_architecture"


@dataclass
class ResearchBudget:
    max_iterations: int = 4
    max_searches: int = 30
    max_sources: int = 25
    max_runtime_seconds: float = 300.0
    max_tokens: int = 80000
    max_cost_usd: float = 2.00

    @classmethod
    def from_depth(cls, depth: ResearchDepth) -> "ResearchBudget":
        if depth == ResearchDepth.QUICK:
            return cls(
                max_iterations=1,
                max_searches=10,
                max_sources=10,
                max_runtime_seconds=90.0,
                max_tokens=25000,
                max_cost_usd=0.50,
            )
        elif depth == ResearchDepth.NORMAL:
            return cls(
                max_iterations=3,
                max_searches=25,
                max_sources=20,
                max_runtime_seconds=240.0,
                max_tokens=60000,
                max_cost_usd=1.50,
            )
        elif depth == ResearchDepth.DEEP:
            return cls(
                max_iterations=6,
                max_searches=50,
                max_sources=40,
                max_runtime_seconds=600.0,
                max_tokens=120000,
                max_cost_usd=3.50,
            )
        elif depth == ResearchDepth.COMPREHENSIVE:
            return cls(
                max_iterations=10,
                max_searches=90,
                max_sources=70,
                max_runtime_seconds=1200.0,
                max_tokens=250000,
                max_cost_usd=8.00,
            )
        return cls()


@dataclass
class ResearchObjective:
    raw_query: str
    core_question: str
    intent_type: str
    depth: ResearchDepth = ResearchDepth.DEEP
    mode: ResearchMode = ResearchMode.GENERAL
    timeframe: str = "2026"
    geographic_scope: str = "Global"
    target_audience: str = "Decision Makers / Engineers / Executives"
    key_entities: List[str] = field(default_factory=list)
    output_format: str = "decision_oriented_report"
    language: str = "English"
    tone: str = "Professional"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "core_question": self.core_question,
            "intent_type": self.intent_type,
            "depth": self.depth.value if isinstance(self.depth, ResearchDepth) else str(self.depth),
            "mode": self.mode.value if isinstance(self.mode, ResearchMode) else str(self.mode),
            "timeframe": self.timeframe,
            "geographic_scope": self.geographic_scope,
            "target_audience": self.target_audience,
            "key_entities": self.key_entities,
            "output_format": self.output_format,
            "language": self.language,
            "tone": self.tone,
        }


@dataclass
class ResearchSubQuestion:
    id: str
    dimension: str  # e.g., "Market", "Competitors", "Tech", "Risks", "Pricing", "Academic"
    question: str
    rationale: str
    search_queries: List[str] = field(default_factory=list)
    completed: bool = False
    evidence_count: int = 0
    confidence_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "dimension": self.dimension,
            "question": self.question,
            "rationale": self.rationale,
            "search_queries": self.search_queries,
            "completed": self.completed,
            "evidence_count": self.evidence_count,
            "confidence_score": self.confidence_score,
        }


@dataclass
class ResearchPlan:
    objective: ResearchObjective
    sub_questions: List[ResearchSubQuestion] = field(default_factory=list)
    budget: ResearchBudget = field(default_factory=ResearchBudget)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective": self.objective.to_dict(),
            "sub_questions": [sq.to_dict() for sq in self.sub_questions],
            "budget": {
                "max_iterations": self.budget.max_iterations,
                "max_searches": self.budget.max_searches,
                "max_sources": self.budget.max_sources,
                "max_runtime_seconds": self.budget.max_runtime_seconds,
            },
            "created_at": self.created_at,
        }


@dataclass
class StopConditions:
    min_confidence_score: float = 0.85
    min_agreement_rate: float = 80.0
    min_sources_analyzed: int = 8
    max_unresolved_contradictions: int = 0
    subquestions_completion_ratio: float = 0.90
