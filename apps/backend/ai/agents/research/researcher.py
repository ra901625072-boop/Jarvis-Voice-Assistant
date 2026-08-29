"""
apps/backend/ai/agents/research/researcher.py
Specialist Research Worker: Dispatches parallel searches, fetches clean text, sanitizes input, and extracts clean atomic evidence into EvidenceStore.
"""
import asyncio
import re
import logging
from typing import List, Dict, Any, Optional

from ai.agents.research.schemas.research import ResearchSubQuestion, ResearchPlan
from ai.agents.research.schemas.source import SourceRecord
from ai.agents.research.memory.source_store import SourceStore
from ai.agents.research.memory.evidence_store import EvidenceStore
from ai.agents.research.tools.web_search import ResearchSearchEngine
from ai.agents.research.tools.web_reader import ResearchWebReader

logger = logging.getLogger("JARVIS.SpecialistResearcher")

NOISY_PHRASES = [
    "cookie", "privacy policy", "terms of use", "subscribe to newsletter",
    "all rights reserved", "advertisement", "sign up today", "click here",
    "jump to content", "main menu", "etymology", "pronunciation", "declension",
    "ipa key", "toggle sidebar", "audio file", "weather forecast", "sign in",
    "sign up", "translations", "noun plural", "adjective", "synonyms", "derived terms"
]


class SpecialistResearcher:
    """
    Coordinates multi-angle search queries across sub-questions, crawls top candidate sites,
    and extracts clean structured evidence.
    """

    def __init__(
        self,
        source_store: SourceStore,
        evidence_store: EvidenceStore,
        llm_generate_func=None
    ):
        self.source_store = source_store
        self.evidence_store = evidence_store
        self._llm_generate = llm_generate_func

    async def investigate_subquestion(
        self,
        sub_q: ResearchSubQuestion,
        max_sources_per_question: int = 4
    ) -> List[SourceRecord]:
        """
        Executes parallel discovery for a sub-question, extracts content, and stores atomic evidence.
        """
        logger.info(f"Investigating sub-question [{sub_q.id}] ({sub_q.dimension}): '{sub_q.question}'")

        # 1. Multi-angle search
        search_candidates = await ResearchSearchEngine.search_queries_parallel(
            sub_q.search_queries,
            max_results_per_query=4
        )

        # 2. Ingest candidates into SourceStore
        processed_sources: List[SourceRecord] = []
        for cand in search_candidates:
            src = self.source_store.add_or_update_source(
                url=cand["url"],
                title=cand.get("title", ""),
                snippet=cand.get("snippet", ""),
                deep_content=cand.get("deep_content", ""),
                discovered_query=cand.get("query", ""),
            )
            if src and src not in processed_sources:
                processed_sources.append(src)

        # 3. Sort by quality and pick top N
        top_sources = sorted(processed_sources, key=lambda s: s.quality.composite_score, reverse=True)[:max_sources_per_question]

        # 4. Crawl full deep content in parallel if not already available
        async def _enrich_source(src: SourceRecord):
            if not src.deep_content:
                text = await ResearchWebReader.extract_clean_text(src.url, timeout=7.0)
                if text:
                    src.deep_content = text
            return src

        crawled_sources = await asyncio.gather(*[_enrich_source(s) for s in top_sources])

        # 5. Extract atomic evidence facts from crawled content
        for src in crawled_sources:
            await self._extract_and_store_evidence(src, sub_q)

        sub_q.completed = True
        sub_q.evidence_count = len(self.evidence_store.get_evidence_for_subquestion(sub_q.id))
        return list(crawled_sources)

    async def _extract_and_store_evidence(
        self,
        source: SourceRecord,
        sub_q: ResearchSubQuestion
    ) -> None:
        """
        Extracts clean factual sentences from source content, strips XML tags, filters UI noise,
        and links evidence into EvidenceStore.
        """
        raw_content = source.deep_content or source.snippet
        if not raw_content:
            return

        # Strip all XML wrapper tags (e.g. <untrusted_external_evidence_data>)
        content = re.sub(r"</?[a-zA-Z0-9_\-]+>", " ", raw_content)
        content = re.sub(r"[ \t]+", " ", content).strip()

        # Split into sentences
        sentences = [s.strip() for s in re.split(r"[.!?]\s+", content) if len(s.strip()) > 25]

        extracted_count = 0
        for sent in sentences[:10]:
            sent_lower = sent.lower()
            # Filter out boilerplate, dictionary, and navigation noise
            if any(noise in sent_lower for noise in NOISY_PHRASES):
                continue
            if sent.startswith("[FILTERED_UNTRUSTED_COMMAND]"):
                continue

            # Add to evidence store
            self.evidence_store.add_evidence(
                source=source,
                excerpt=sent,
                sub_question_id=sub_q.id,
                confidence=source.quality.composite_score
            )
            extracted_count += 1
            if extracted_count >= 5:
                break
