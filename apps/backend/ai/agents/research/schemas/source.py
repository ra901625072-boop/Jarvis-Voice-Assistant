"""
apps/backend/ai/agents/research/schemas/source.py
Data models for Source records, S1-S8 Source Tiers, Primary vs Secondary Classification, and Quality scoring.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional
import time


class SourceTier(str, Enum):
    S1_PEER_REVIEWED = "S1 — Original Peer-Reviewed Research"        # 0.95 (Primary)
    S2_PREPRINT_TECH = "S2 — Preprint / Technical Working Paper"       # 0.91 (Primary)
    S3_GOV_LAB_UNIV = "S3 — Government / University / National Lab"   # 0.93 (Primary)
    S4_OFFICIAL_DOCS = "S4 — Official Company Docs / Technical Repos"  # 0.88 (Primary/Secondary)
    S5_REPUTABLE_JOURNALISM = "S5 — Reputable Scientific & Tech Journalism" # 0.82 (Secondary)
    S6_GENERAL_WEB = "S6 — General Reference & Informational Web"     # 0.60 (Secondary)
    S7_COMMUNITY_FORUM = "S7 — Community Discussions / Forums / Blogs"  # 0.45 (Secondary)
    S8_LOW_QUALITY = "S8 — Low Authority / Aggregator"                # 0.20 (Secondary)

    # Legacy Aliases for backwards compatibility
    OFFICIAL_GOV = "S3 — Government / University / National Lab"
    ACADEMIC_RESEARCH = "S1 — Original Peer-Reviewed Research"
    OFFICIAL_DOCS = "S4 — Official Company Docs / Technical Repos"
    MAJOR_JOURNALISM = "S5 — Reputable Scientific & Tech Journalism"
    INDUSTRY_REPORT = "S4 — Official Company Docs / Technical Repos"
    EXPERT_ANALYSIS = "S5 — Reputable Scientific & Tech Journalism"
    FORUM_COMMUNITY = "S7 — Community Discussions / Forums / Blogs"
    GENERAL_WEB = "S6 — General Reference & Informational Web"
    LOW_QUALITY = "S8 — Low Authority / Aggregator"


TIER_BASE_SCORES: Dict[SourceTier, float] = {
    SourceTier.S1_PEER_REVIEWED: 0.95,
    SourceTier.S2_PREPRINT_TECH: 0.91,
    SourceTier.S3_GOV_LAB_UNIV: 0.93,
    SourceTier.S4_OFFICIAL_DOCS: 0.88,
    SourceTier.S5_REPUTABLE_JOURNALISM: 0.82,
    SourceTier.S6_GENERAL_WEB: 0.60,
    SourceTier.S7_COMMUNITY_FORUM: 0.45,
    SourceTier.S8_LOW_QUALITY: 0.20,
}

PRIMARY_TIERS = {
    SourceTier.S1_PEER_REVIEWED,
    SourceTier.S2_PREPRINT_TECH,
    SourceTier.S3_GOV_LAB_UNIV,
    SourceTier.S4_OFFICIAL_DOCS,
}


@dataclass
class SourceQualityScore:
    authority: float = 0.50
    relevance: float = 0.50
    freshness: float = 0.80
    primary_source_score: float = 0.50
    evidence_specificity: float = 0.50
    bias_penalty: float = 0.0
    spam_penalty: float = 0.0

    @property
    def composite_score(self) -> float:
        score = (
            0.35 * self.authority +
            0.25 * self.relevance +
            0.15 * self.freshness +
            0.15 * self.primary_source_score +
            0.10 * self.evidence_specificity -
            self.bias_penalty -
            self.spam_penalty
        )
        return max(0.05, min(1.0, round(score, 3)))


@dataclass
class SourceRecord:
    id: int
    url: str
    title: str
    domain: str
    source_tier: SourceTier = SourceTier.S6_GENERAL_WEB
    quality: SourceQualityScore = field(default_factory=SourceQualityScore)
    snippet: str = ""
    deep_content: str = ""
    discovered_query: str = ""
    fetched_at: float = field(default_factory=time.time)
    http_status: int = 200
    is_trusted: bool = True
    is_primary: bool = False
    author: Optional[str] = None
    publication_date: Optional[str] = None

    def __post_init__(self):
        if self.source_tier in PRIMARY_TIERS:
            self.is_primary = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "domain": self.domain,
            "source_tier": self.source_tier.value if isinstance(self.source_tier, SourceTier) else str(self.source_tier),
            "is_primary": self.is_primary,
            "quality_score": self.quality.composite_score,
            "author": self.author,
            "publication_date": self.publication_date,
            "snippet": self.snippet,
            "has_deep_content": bool(self.deep_content),
            "discovered_query": self.discovered_query,
            "fetched_at": self.fetched_at,
        }
