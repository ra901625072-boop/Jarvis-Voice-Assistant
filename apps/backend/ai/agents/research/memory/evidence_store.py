"""
apps/backend/ai/agents/research/memory/evidence_store.py
Structured Evidence Store & Evidence Graph for Complete Research Traceability.
Provides the data link: Conclusion -> Claim -> Evidence Excerpt -> Source Record.
"""
from typing import Dict, List, Optional, Set, Any
import logging

from ai.agents.research.schemas.evidence import EvidenceItem, ClaimItem, ContradictionRecord
from ai.agents.research.schemas.source import SourceRecord

logger = logging.getLogger("JARVIS.ResearchMemory.EvidenceStore")


class EvidenceStore:
    """
    Manages atomic extracted evidence items and maintains the relational graph connecting
    sub-questions, claims, evidence snippets, and source documents.
    """

    def __init__(self):
        self._evidence: Dict[str, EvidenceItem] = {}
        self._next_evd_idx: int = 1
        self._evidence_by_source: Dict[int, List[str]] = {}
        self._evidence_by_subquestion: Dict[str, List[str]] = {}

    def add_evidence(
        self,
        source: SourceRecord,
        excerpt: str,
        sub_question_id: Optional[str] = None,
        confidence: float = 0.85
    ) -> EvidenceItem:
        """Adds a clean extracted atomic evidence snippet connected to its source."""
        evd_id = f"EVD-{self._next_evd_idx:03d}"
        self._next_evd_idx += 1

        tier_name = source.source_tier.value if hasattr(source.source_tier, "value") else str(source.source_tier)
        item = EvidenceItem(
            id=evd_id,
            source_id=source.id,
            source_url=source.url,
            source_title=source.title,
            source_tier=tier_name,
            excerpt=excerpt.strip(),
            confidence=confidence,
            sub_question_id=sub_question_id,
        )

        self._evidence[evd_id] = item

        if source.id not in self._evidence_by_source:
            self._evidence_by_source[source.id] = []
        self._evidence_by_source[source.id].append(evd_id)

        if sub_question_id:
            if sub_question_id not in self._evidence_by_subquestion:
                self._evidence_by_subquestion[sub_question_id] = []
            self._evidence_by_subquestion[sub_question_id].append(evd_id)

        return item

    def get_evidence(self, evidence_id: str) -> Optional[EvidenceItem]:
        return self._evidence.get(evidence_id)

    def get_all_evidence(self) -> List[EvidenceItem]:
        return list(self._evidence.values())

    def get_evidence_for_source(self, source_id: int) -> List[EvidenceItem]:
        evd_ids = self._evidence_by_source.get(source_id, [])
        return [self._evidence[eid] for eid in evd_ids if eid in self._evidence]

    def get_evidence_for_subquestion(self, sub_question_id: str) -> List[EvidenceItem]:
        evd_ids = self._evidence_by_subquestion.get(sub_question_id, [])
        return [self._evidence[eid] for eid in evd_ids if eid in self._evidence]

    def count(self) -> int:
        return len(self._evidence)
