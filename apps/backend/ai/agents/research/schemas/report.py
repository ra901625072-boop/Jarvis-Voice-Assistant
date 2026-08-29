"""
apps/backend/ai/agents/research/schemas/report.py
Data models for 17-Section Publication-Grade Research Reports, Sections, Citations, Audit Trails, and Confidence Dashboards.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import time


@dataclass
class CitationItem:
    id: int
    title: str
    url: str
    domain: str
    source_tier: str
    authority_score: float
    inline_tag: str  # e.g., "[1]"
    is_primary: bool = False
    author: Optional[str] = None
    publication_date: Optional[str] = None
    confidence: str = "High"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "domain": self.domain,
            "source_tier": self.source_tier,
            "authority_score": self.authority_score,
            "inline_tag": self.inline_tag,
            "is_primary": self.is_primary,
            "author": self.author,
            "publication_date": self.publication_date,
            "confidence": self.confidence,
        }


@dataclass
class ResearchAuditTrail:
    queries_executed: int = 0
    sources_discovered: int = 0
    sources_selected: int = 0
    primary_sources: int = 0
    secondary_sources: int = 0
    sources_rejected: int = 0
    claims_extracted: int = 0
    claims_cross_validated: int = 0
    conflicting_claims: int = 0
    unresolved_claims: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "queries_executed": self.queries_executed,
            "sources_discovered": self.sources_discovered,
            "sources_selected": self.sources_selected,
            "primary_sources": self.primary_sources,
            "secondary_sources": self.secondary_sources,
            "sources_rejected": self.sources_rejected,
            "claims_extracted": self.claims_extracted,
            "claims_cross_validated": self.claims_cross_validated,
            "conflicting_claims": self.conflicting_claims,
            "unresolved_claims": self.unresolved_claims,
        }


@dataclass
class ConfidenceAssessmentRow:
    topic: str
    confidence: str  # Very High, High, Medium, Low/Uncertain
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass
class ConfidenceDashboard:
    overall_confidence_score: float = 0.85
    overall_confidence_level: str = "HIGH"  # HIGH / MEDIUM / LOW
    source_authority_score: float = 85.0
    fact_agreement_rate: float = 90.0
    source_diversity_score: float = 80.0
    citation_quality_score: float = 90.0
    completeness_score: float = 85.0
    total_sources_evaluated: int = 0
    total_claims_verified: int = 0
    contradictions_resolved_count: int = 0
    tier_breakdown: Dict[str, int] = field(default_factory=dict)
    audit_trail: ResearchAuditTrail = field(default_factory=ResearchAuditTrail)
    confidence_assessment_table: List[ConfidenceAssessmentRow] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_confidence_score": round(self.overall_confidence_score, 2),
            "overall_confidence_level": self.overall_confidence_level,
            "source_authority_score": round(self.source_authority_score, 1),
            "fact_agreement_rate": round(self.fact_agreement_rate, 1),
            "source_diversity_score": round(self.source_diversity_score, 1),
            "citation_quality_score": round(self.citation_quality_score, 1),
            "completeness_score": round(self.completeness_score, 1),
            "total_sources_evaluated": self.total_sources_evaluated,
            "total_claims_verified": self.total_claims_verified,
            "contradictions_resolved_count": self.contradictions_resolved_count,
            "tier_breakdown": self.tier_breakdown,
            "audit_trail": self.audit_trail.to_dict(),
            "confidence_assessment_table": [r.to_dict() for r in self.confidence_assessment_table],
        }


@dataclass
class ReportSection:
    heading: str
    content: str
    level: int = 2
    subsections: List["ReportSection"] = field(default_factory=list)

    def to_markdown(self) -> str:
        prefix = "#" * self.level
        md = f"{prefix} {self.heading}\n\n{self.content}\n\n"
        for sub in self.subsections:
            md += sub.to_markdown()
        return md


@dataclass
class ResearchReport:
    title: str
    objective: str
    executive_summary: str
    depth: str
    created_at: float = field(default_factory=time.time)
    sections: List[ReportSection] = field(default_factory=list)
    citations: List[CitationItem] = field(default_factory=list)
    dashboard: ConfidenceDashboard = field(default_factory=ConfidenceDashboard)
    raw_markdown: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "objective": self.objective,
            "executive_summary": self.executive_summary,
            "depth": self.depth,
            "created_at": self.created_at,
            "citations": [c.to_dict() for c in self.citations],
            "dashboard": self.dashboard.to_dict(),
            "raw_markdown": self.raw_markdown,
        }
