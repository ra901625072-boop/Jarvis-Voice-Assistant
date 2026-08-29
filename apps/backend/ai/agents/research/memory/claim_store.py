"""
apps/backend/ai/agents/research/memory/claim_store.py
Claim Store & Contradiction Registry for Fact Verification and Truth Resolution.
"""
from typing import Dict, List, Optional, Any
import logging

from ai.agents.research.schemas.evidence import ClaimItem, ClaimStatus, ContradictionRecord, ContradictionType

logger = logging.getLogger("JARVIS.ResearchMemory.ClaimStore")


class ClaimStore:
    """
    Manages structured research claims, their verification statuses, and contradiction linkages.
    """

    def __init__(self):
        self._claims: Dict[str, ClaimItem] = {}
        self._contradictions: Dict[str, ContradictionRecord] = {}
        self._next_clm_idx: int = 1
        self._next_ctr_idx: int = 1

    def add_claim(
        self,
        statement: str,
        dimension: str = "General",
        sub_question_id: Optional[str] = None,
        evidence_ids: Optional[List[str]] = None,
        source_ids: Optional[List[int]] = None,
        confidence_score: float = 0.85,
        is_numerical: bool = False,
        extracted_number: Optional[float] = None,
        unit: str = ""
    ) -> ClaimItem:
        """Registers a new factual or analytical claim."""
        clm_id = f"CLM-{self._next_clm_idx:03d}"
        self._next_clm_idx += 1

        claim = ClaimItem(
            id=clm_id,
            statement=statement.strip(),
            sub_question_id=sub_question_id,
            dimension=dimension,
            evidence_ids=evidence_ids or [],
            source_ids=source_ids or [],
            confidence_score=confidence_score,
            status=ClaimStatus.UNVERIFIED,
            is_numerical=is_numerical,
            extracted_number=extracted_number,
            unit=unit,
        )
        self._claims[clm_id] = claim
        return claim

    def get_claim(self, claim_id: str) -> Optional[ClaimItem]:
        return self._claims.get(claim_id)

    def get_all_claims(self) -> List[ClaimItem]:
        return list(self._claims.values())

    def update_claim_status(self, claim_id: str, status: ClaimStatus, confidence_score: Optional[float] = None) -> None:
        if claim_id in self._claims:
            self._claims[claim_id].status = status
            if confidence_score is not None:
                self._claims[claim_id].confidence_score = confidence_score

    def record_contradiction(
        self,
        claim_a: ClaimItem,
        claim_b: ClaimItem,
        contradiction_type: ContradictionType,
        explanation: str,
        claim_a_source: str = "",
        claim_b_source: str = ""
    ) -> ContradictionRecord:
        """Records a detected contradiction between two claims."""
        ctr_id = f"CTR-{self._next_ctr_idx:03d}"
        self._next_ctr_idx += 1

        record = ContradictionRecord(
            id=ctr_id,
            claim_a_id=claim_a.id,
            claim_a_text=claim_a.statement,
            claim_a_source=claim_a_source,
            claim_b_id=claim_b.id,
            claim_b_text=claim_b.statement,
            claim_b_source=claim_b_source,
            contradiction_type=contradiction_type,
            explanation=explanation,
            resolved=False,
        )

        self._contradictions[ctr_id] = record
        claim_a.contradiction_ids.append(ctr_id)
        claim_b.contradiction_ids.append(ctr_id)
        claim_a.status = ClaimStatus.CONTESTED
        claim_b.status = ClaimStatus.CONTESTED

        return record

    def resolve_contradiction(self, contradiction_id: str, resolution_note: str) -> None:
        if contradiction_id in self._contradictions:
            ctr = self._contradictions[contradiction_id]
            ctr.resolved = True
            ctr.resolution_note = resolution_note

    def get_all_contradictions(self) -> List[ContradictionRecord]:
        return list(self._contradictions.values())

    def count(self) -> int:
        return len(self._claims)
