"""
apps/backend/ai/agents/research/__init__.py
"""
from ai.agents.research.agent import DeepResearchAgent
from ai.agents.research.manager import ResearchManager
from ai.agents.research.planner import ResearchPlanner
from ai.agents.research.researcher import SpecialistResearcher
from ai.agents.research.verifier import FactVerifier
from ai.agents.research.critic import ResearchCritic
from ai.agents.research.synthesizer import ResearchSynthesizer
from ai.agents.research.reporter import ResearchReportGenerator
from ai.agents.research.schemas import (
    ResearchDepth,
    ResearchMode,
    ResearchBudget,
    ResearchObjective,
    ResearchSubQuestion,
    ResearchPlan,
    SourceRecord,
    SourceTier,
    EvidenceItem,
    ClaimItem,
    ContradictionRecord,
    ResearchReport,
    ConfidenceDashboard,
)

__all__ = [
    "DeepResearchAgent",
    "ResearchManager",
    "ResearchPlanner",
    "SpecialistResearcher",
    "FactVerifier",
    "ResearchCritic",
    "ResearchSynthesizer",
    "ResearchReportGenerator",
    "ResearchDepth",
    "ResearchMode",
    "ResearchBudget",
    "ResearchObjective",
    "ResearchSubQuestion",
    "ResearchPlan",
    "SourceRecord",
    "SourceTier",
    "EvidenceItem",
    "ClaimItem",
    "ContradictionRecord",
    "ResearchReport",
    "ConfidenceDashboard",
]
