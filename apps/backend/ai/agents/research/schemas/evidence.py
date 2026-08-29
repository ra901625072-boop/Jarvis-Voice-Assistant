"""
apps/backend/ai/agents/research/schemas/evidence.py
Data models for Claims, Evidence Items, Contradiction Records, and Evidence Graph.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional
import time


class ClaimStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    CONTESTED = "contested"
    REFUTED = "refuted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ContradictionType(str, Enum):
    NUMERICAL_DISCREPANCY = "numerical_discrepancy"  # e.g., $10B vs $7B
    TEMPORAL_MISMATCH = "temporal_mismatch"          # e.g., 2024 data vs 2026 forecast
    GEOGRAPHIC_SCOPE = "geographic_scope"            # e.g., US market vs Global
    METHODOLOGY_DIFFERENCE = "methodology_difference" # e.g., TAM vs SAM vs SAM-AI
    FACTUAL_CONFLICT = "factual_conflict"            # Direct contradiction (supports vs opposes)


@dataclass
class EvidenceItem:
    id: str  # EVD-001
    source_id: int
    source_url: str
    source_title: str
    source_tier: str
    excerpt: str
    confidence: float = 0.85
    sub_question_id: Optional[str] = None
    extracted_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "source_tier": self.source_tier,
            "excerpt": self.excerpt,
            "confidence": self.confidence,
            "sub_question_id": self.sub_question_id,
            "extracted_at": self.extracted_at,
        }


@dataclass
class ContradictionRecord:
    id: str
    claim_a_id: str
    claim_a_text: str
    claim_a_source: str
    claim_b_id: str
    claim_b_text: str
    claim_b_source: str
    contradiction_type: ContradictionType
    explanation: str
    resolved: bool = False
    resolution_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "claim_a_id": self.claim_a_id,
            "claim_a_text": self.claim_a_text,
            "claim_a_source": self.claim_a_source,
            "claim_b_id": self.claim_b_id,
            "claim_b_text": self.claim_b_text,
            "claim_b_source": self.claim_b_source,
            "contradiction_type": self.contradiction_type.value if isinstance(self.contradiction_type, ContradictionType) else str(self.contradiction_type),
            "explanation": self.explanation,
            "resolved": self.resolved,
            "resolution_note": self.resolution_note,
        }


@dataclass
class ClaimItem:
    id: str  # CLM-001
    statement: str
    sub_question_id: Optional[str] = None
    dimension: str = "General"
    evidence_ids: List[str] = field(default_factory=list)
    source_ids: List[int] = field(default_factory=list)
    confidence_score: float = 0.85
    status: ClaimStatus = ClaimStatus.UNVERIFIED
    contradiction_ids: List[str] = field(default_factory=list)
    is_numerical: bool = False
    extracted_number: Optional[float] = None
    unit: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "sub_question_id": self.sub_question_id,
            "dimension": self.dimension,
            "evidence_ids": self.evidence_ids,
            "source_ids": self.source_ids,
            "confidence_score": self.confidence_score,
            "status": self.status.value if isinstance(self.status, ClaimStatus) else str(self.status),
            "contradiction_ids": self.contradiction_ids,
            "is_numerical": self.is_numerical,
            "extracted_number": self.extracted_number,
            "unit": self.unit,
        }
