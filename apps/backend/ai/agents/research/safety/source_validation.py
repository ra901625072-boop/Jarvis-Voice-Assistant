"""
apps/backend/ai/agents/research/safety/source_validation.py
SSRF Guard, URL Security, and Source Quality / Authority Classification with S1-S8 Tiers.
"""
import re
import ipaddress
import logging
from urllib.parse import urlparse
from typing import Tuple, Optional

from ai.agents.research.schemas.source import SourceTier, SourceQualityScore, TIER_BASE_SCORES

logger = logging.getLogger("JARVIS.ResearchSafety.SourceValidation")

# Blocked IP ranges & hostnames for SSRF protection
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),        # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),     # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),    # Private Class C
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local & Cloud metadata (AWS, GCP, Azure)
    ipaddress.ip_network("fc00::/7"),          # IPv6 Private
    ipaddress.ip_network("::1/128"),           # IPv6 Loopback
]

BLOCKED_HOSTNAMES = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "metadata.google.internal",
    "instance-data",
}

SPAM_TLDS = {
    ".click", ".top", ".xyz", ".link", ".work", ".stream", ".gdn", ".loan", ".racing", ".bid",
    ".party", ".country", ".science", ".date", ".faith", ".accountant"
}


class SourceValidator:
    """
    Validates URLs against SSRF attacks and computes comprehensive domain authority scoring across S1-S8 tiers.
    """

    @classmethod
    def is_safe_url(cls, url: str) -> Tuple[bool, str]:
        """
        Validates URL scheme and checks for SSRF targets (private IPs, cloud metadata).
        Returns (is_safe, error_reason).
        """
        if not url or not isinstance(url, str):
            return False, "Empty or invalid URL string"

        try:
            parsed = urlparse(url)
        except Exception as e:
            return False, f"Failed to parse URL: {e}"

        if parsed.scheme not in ("http", "https"):
            return False, f"Unsupported URL scheme '{parsed.scheme}'. Only http/https permitted."

        hostname = parsed.hostname
        if not hostname:
            return False, "Missing hostname in URL"

        hostname_lower = hostname.lower()

        if hostname_lower in BLOCKED_HOSTNAMES:
            logger.warning(f"Blocked SSRF attempt targeting '{hostname_lower}' in URL: {url}")
            return False, f"SSRF Protection: Access to '{hostname_lower}' is strictly blocked."

        # Check if hostname is an IP address
        try:
            ip_obj = ipaddress.ip_address(hostname_lower)
            for net in BLOCKED_IP_NETWORKS:
                if ip_obj in net:
                    logger.warning(f"Blocked SSRF attempt targeting private IP '{ip_obj}' in URL: {url}")
                    return False, f"SSRF Protection: Access to private IP '{ip_obj}' is blocked."
        except ValueError:
            # Not an IP literal, standard hostname
            pass

        return True, ""

    @classmethod
    def classify_source_tier(cls, url: str) -> SourceTier:
        """
        Determines the authoritative S1-S8 tier of a source based on its URL and domain.
        """
        if not url:
            return SourceTier.S6_GENERAL_WEB

        url_lower = url.lower()
        domain = urlparse(url_lower).netloc

        # 1. S1 — Peer-Reviewed Academic & Scientific Research (Nature, Science, IEEE, PubMed, ACM, Springer, ScienceDirect)
        if any(d in url_lower for d in [
            "nature.com/articles", "science.org/doi", "ieee.org", "ncbi.nlm.nih.gov",
            "semanticscholar.org", "acm.org", "sciencedirect.com", "springer.com",
            "aps.org", "iop.org", "cell.com", "thelancet.com"
        ]):
            return SourceTier.S1_PEER_REVIEWED

        # 2. S2 — Preprint & Technical Working Papers (arXiv, bioRxiv, IACR, OpenReview)
        if any(d in url_lower for d in [
            "arxiv.org", "biorxiv.org", "medrxiv.org", "eprint.iacr.org", "openreview.net"
        ]):
            return SourceTier.S2_PREPRINT_TECH

        # 3. S3 — Government / University / National Lab (.gov, .mil, nist.gov, cern.ch, .edu, .ac.)
        if any(d in url_lower for d in [
            ".gov", ".mil", ".gov.", "nist.gov", "cern.ch", "lanl.gov", "llnl.gov", "ornl.gov",
            "bnl.gov", "nasa.gov", "un.org", "worldbank.org", "imf.org", "who.int", ".edu", ".ac."
        ]):
            return SourceTier.S3_GOV_LAB_UNIV

        # 4. S4 — Official Company Technical Docs & Repos
        if any(d in url_lower for d in [
            "docs.", "developer.", "github.com", "learn.microsoft.com", "platform.openai.com",
            "modelcontextprotocol.io", "cloud.google.com", "kubernetes.io", "docs.min.io",
            "playwright.dev", "trafilatura.readthedocs.io", "cohere.com", "keycloak.org",
            "opensearch.org", "gitlab.com", "pypi.org", "npmjs.com", "ibm.com/quantum",
            "research.ibm.com", "quantumai.google"
        ]):
            return SourceTier.S4_OFFICIAL_DOCS

        # 5. S5 — Reputable Scientific & Tech Journalism
        if any(d in url_lower for d in [
            "quantamagazine.org", "phys.org", "scientificamerican.com", "newscientist.com",
            "techcrunch.com", "bloomberg.com", "reuters.com", "wsj.com", "ft.com",
            "wired.com", "theverge.com", "arstechnica.com", "venturebeat.com", "gartner.com",
            "statista.com", "forrester.com"
        ]):
            return SourceTier.S5_REPUTABLE_JOURNALISM

        # 6. S7 — Community Discussions / Forums / Blogs
        if any(d in url_lower for d in [
            "reddit.com", "news.ycombinator.com", "stackoverflow.com", "quora.com", "discord.com",
            "medium.com", "dev.to", "towardsdatascience.com", "substack.com"
        ]):
            return SourceTier.S7_COMMUNITY_FORUM

        # 7. S8 — Check for Low Quality / Spam TLDs
        if any(domain.endswith(tld) for tld in SPAM_TLDS):
            return SourceTier.S8_LOW_QUALITY

        # 8. S6 — General Web & Reference
        return SourceTier.S6_GENERAL_WEB

    @classmethod
    def score_source(
        cls,
        url: str,
        title: str = "",
        snippet: str = "",
        deep_content: str = "",
        discovered_query: str = ""
    ) -> SourceQualityScore:
        """
        Calculates multi-dimensional quality metrics for a source.
        """
        tier = cls.classify_source_tier(url)
        base_authority = TIER_BASE_SCORES.get(tier, 0.60)

        # Relevance heuristics based on title/snippet keyword matching with query
        relevance = 0.60
        if discovered_query:
            query_words = set(re.findall(r"\b\w{4,}\b", discovered_query.lower()))
            if query_words:
                text_to_check = f"{title} {snippet} {deep_content[:500]}".lower()
                matches = sum(1 for w in query_words if w in text_to_check)
                relevance = min(1.0, 0.40 + (matches / len(query_words)) * 0.60)

        # Specificity / Content richness
        specificity = 0.50
        if deep_content and len(deep_content) > 300:
            specificity = 0.85
        elif snippet and len(snippet) > 80:
            specificity = 0.65

        # Primary source heuristic
        is_primary = tier in (SourceTier.S1_PEER_REVIEWED, SourceTier.S2_PREPRINT_TECH, SourceTier.S3_GOV_LAB_UNIV, SourceTier.S4_OFFICIAL_DOCS)
        primary_source_score = 0.95 if is_primary else 0.50

        # Spam penalties
        spam_penalty = 0.40 if tier == SourceTier.S8_LOW_QUALITY else 0.0

        return SourceQualityScore(
            authority=base_authority,
            relevance=relevance,
            freshness=0.85,
            primary_source_score=primary_source_score,
            evidence_specificity=specificity,
            bias_penalty=0.0,
            spam_penalty=spam_penalty
        )
