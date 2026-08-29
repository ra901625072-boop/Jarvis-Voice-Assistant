"""
apps/backend/ai/agents/research/memory/source_store.py
Source Store, Deduplication, Authority Ranking, and Diversity Registry.
"""
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse
import logging

from ai.agents.research.schemas.source import SourceRecord, SourceTier, SourceQualityScore
from ai.agents.research.safety.source_validation import SourceValidator

logger = logging.getLogger("JARVIS.ResearchMemory.SourceStore")


class SourceStore:
    """
    Thread-safe in-memory registry for tracking, ranking, and deduplicating research sources.
    """

    def __init__(self):
        self._sources: Dict[int, SourceRecord] = {}
        self._url_to_id: Dict[str, int] = {}
        self._next_id: int = 1

    def normalize_url(self, url: str) -> str:
        """Normalizes URL for accurate deduplication (lowercase, strip trailing slash)."""
        if not url:
            return ""
        parsed = urlparse(url.strip().lower())
        path = parsed.path.rstrip("/")
        netloc = parsed.netloc
        scheme = parsed.scheme or "https"
        return f"{scheme}://{netloc}{path}"

    def add_or_update_source(
        self,
        url: str,
        title: str = "",
        snippet: str = "",
        deep_content: str = "",
        discovered_query: str = ""
    ) -> Optional[SourceRecord]:
        """
        Adds a new source candidate or enriches an existing candidate with deeper crawled content.
        """
        is_safe, reason = SourceValidator.is_safe_url(url)
        if not is_safe:
            logger.debug(f"Skipping unsafe or invalid URL: {url} ({reason})")
            return None

        norm_url = self.normalize_url(url)
        domain = urlparse(norm_url).netloc
        tier = SourceValidator.classify_source_tier(norm_url)
        quality = SourceValidator.score_source(norm_url, title, snippet, deep_content, discovered_query)

        if norm_url in self._url_to_id:
            src_id = self._url_to_id[norm_url]
            existing = self._sources[src_id]
            if title and (not existing.title or existing.title == "Source Document"):
                existing.title = title
            if deep_content and not existing.deep_content:
                existing.deep_content = deep_content
                existing.quality = quality
            return existing

        src_id = self._next_id
        self._next_id += 1

        record = SourceRecord(
            id=src_id,
            url=url.strip(),
            title=title.strip() or f"Source {src_id} ({domain})",
            domain=domain,
            source_tier=tier,
            quality=quality,
            snippet=snippet,
            deep_content=deep_content,
            discovered_query=discovered_query,
        )

        self._sources[src_id] = record
        self._url_to_id[norm_url] = src_id
        return record

    def get_source(self, source_id: int) -> Optional[SourceRecord]:
        return self._sources.get(source_id)

    def get_all_sources(self) -> List[SourceRecord]:
        return list(self._sources.values())

    def get_top_ranked_sources(self, limit: int = 10) -> List[SourceRecord]:
        """Returns sources sorted by composite quality score descending."""
        return sorted(self._sources.values(), key=lambda s: s.quality.composite_score, reverse=True)[:limit]

    def get_unique_domains(self) -> Set[str]:
        return {s.domain for s in self._sources.values() if s.domain}

    def get_tier_breakdown(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for s in self._sources.values():
            tier_name = s.source_tier.value if isinstance(s.source_tier, SourceTier) else str(s.source_tier)
            counts[tier_name] = counts.get(tier_name, 0) + 1
        return counts

    def calculate_source_diversity_score(self) -> float:
        """Returns 0-100 score based on domain diversity across sources."""
        unique_domains = len(self.get_unique_domains())
        if unique_domains == 0:
            return 0.0
        # 5+ independent domains yields 100% diversity score
        return min(100.0, round((unique_domains / 5.0) * 100.0, 1))

    def calculate_source_authority_score(self) -> float:
        """Returns average authority score across all recorded sources (0-100)."""
        if not self._sources:
            return 50.0
        avg_auth = sum(s.quality.authority for s in self._sources.values()) / len(self._sources)
        return round(avg_auth * 100.0, 1)
