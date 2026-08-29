"""
apps/backend/ai/agents/research/tools/citation_tool.py
Citation Engine & Authentic Reference Registry for Publication-Grade Research Reports.
"""
from typing import List, Dict, Any, Optional
import logging

from ai.agents.research.schemas.report import CitationItem
from ai.agents.research.schemas.source import SourceRecord, SourceTier, PRIMARY_TIERS

logger = logging.getLogger("JARVIS.ResearchTools.CitationTracker")


class CitationTracker:
    """
    Tracks and registers authentic citation links and formats inline bracket citations [1], [2].
    """

    def __init__(self):
        self._citations: Dict[int, CitationItem] = {}
        self._url_to_id: Dict[str, int] = {}
        self._next_id = 1

    def register_source(self, source: SourceRecord) -> CitationItem:
        """Registers a source record and returns its CitationItem with inline tag."""
        norm_url = source.url.strip()
        if norm_url in self._url_to_id:
            return self._citations[self._url_to_id[norm_url]]

        cite_id = self._next_id
        self._next_id += 1

        tier_name = source.source_tier.value if hasattr(source.source_tier, "value") else str(source.source_tier)
        is_primary = getattr(source, "is_primary", False) or (source.source_tier in PRIMARY_TIERS)
        confidence = "High" if source.quality.authority >= 0.80 else ("Medium" if source.quality.authority >= 0.60 else "Moderate")

        item = CitationItem(
            id=cite_id,
            title=source.title or f"Source Document {cite_id}",
            url=source.url,
            domain=source.domain,
            source_tier=tier_name,
            authority_score=source.quality.authority,
            inline_tag=f"[{cite_id}]",
            is_primary=is_primary,
            author=source.author or source.domain,
            publication_date=source.publication_date,
            confidence=confidence,
        )

        self._citations[cite_id] = item
        self._url_to_id[norm_url] = cite_id
        return item

    def get_citation_by_id(self, cite_id: int) -> Optional[CitationItem]:
        return self._citations.get(cite_id)

    def get_all_citations(self) -> List[CitationItem]:
        return list(self._citations.values())

    def format_citation_index_markdown(self) -> str:
        """Produces a structured References & Citations section with hyperlinks, S1-S8 tier tags, and Primary/Secondary status."""
        if not self._citations:
            return ""

        md = "## 16. References & Verified Sources\n\n"
        for cite in sorted(self._citations.values(), key=lambda c: c.id):
            auth_pct = int(cite.authority_score * 100)
            src_kind = "Primary Source" if cite.is_primary else "Secondary Source"
            date_str = f" | Published: `{cite.publication_date}`" if cite.publication_date else ""
            md += f"- **[{cite.id}] [{cite.title}]({cite.url})**  \n"
            md += f"  > **Classification:** `{cite.source_tier}` ({src_kind})\n"
            md += f"  > **Authority Score:** `{auth_pct}%` | **Domain:** `{cite.domain}` | **Confidence:** `{cite.confidence}`{date_str}\n\n"
        return md
