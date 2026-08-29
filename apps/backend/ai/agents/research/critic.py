"""
apps/backend/ai/agents/research/critic.py
Research Critic & Gap Detector: Evaluates research completeness, identifies missing dimensions, and generates targeted follow-up queries.
"""
import logging
from typing import List, Dict, Any, Tuple

from ai.agents.research.schemas.research import ResearchPlan, ResearchSubQuestion
from ai.agents.research.memory.evidence_store import EvidenceStore
from ai.agents.research.memory.source_store import SourceStore
from ai.agents.research.memory.claim_store import ClaimStore

logger = logging.getLogger("JARVIS.ResearchCritic")


class ResearchCritic:
    """
    Evaluates evidence coverage across all plan sub-questions, detects knowledge gaps,
    and proposes targeted follow-up query angles for subsequent research rounds.
    """

    def __init__(
        self,
        evidence_store: EvidenceStore,
        source_store: SourceStore,
        claim_store: ClaimStore,
        llm_generate_func=None
    ):
        self.evidence_store = evidence_store
        self.source_store = source_store
        self.claim_store = claim_store
        self._llm_generate = llm_generate_func

    def evaluate_research_gaps(self, plan: ResearchPlan) -> Dict[str, Any]:
        """
        Analyzes sub-question coverage and identifies dimensions with insufficient evidence.
        """
        gaps: List[str] = []
        followup_queries: List[str] = []
        completed_count = 0
        total_sub_qs = len(plan.sub_questions)

        for sq in plan.sub_questions:
            evd_list = self.evidence_store.get_evidence_for_subquestion(sq.id)
            if len(evd_list) < 2:
                gaps.append(f"Insufficient evidence for [{sq.dimension}]: '{sq.question}' (Only {len(evd_list)} source facts)")
                # Generate refined queries targeted at this gap
                core_terms = " ".join(sq.question.split()[:5])
                followup_queries.append(f"{core_terms} official benchmark data")
                followup_queries.append(f"{core_terms} detailed technical breakdown")
            else:
                completed_count += 1

        # Check source diversity
        diversity_score = self.source_store.calculate_source_diversity_score()
        if diversity_score < 60.0:
            gaps.append("Low source diversity: Research is concentrated in fewer than 3 independent domains.")
            followup_queries.append(f"{plan.objective.core_question} academic research paper analysis")
            followup_queries.append(f"{plan.objective.core_question} open source community discussion")

        # Completeness score
        coverage_ratio = (completed_count / max(1, total_sub_qs))
        completeness_score = round(coverage_ratio * 100.0, 1)

        has_critical_gaps = len(gaps) > 0 and completeness_score < 80.0

        logger.info(f"Critic Evaluation: Completeness={completeness_score}%, Critical Gaps={len(gaps)}")
        return {
            "has_critical_gaps": has_critical_gaps,
            "completeness_score": completeness_score,
            "identified_gaps": gaps,
            "recommended_followup_queries": followup_queries[:6],
        }
