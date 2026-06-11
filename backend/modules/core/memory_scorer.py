"""
memory_scorer.py
----------------
Standalone engine for classifying and scoring memory entries.
Used by MemoryManager to enrich every stored memory with:
  - importance score (1–10)
  - memory type (semantic / episodic / procedural / working)
  - project namespace (jarvis / nova / general / ...)
  - content tags (list of keywords)
"""

import re
import logging
from typing import List, Tuple

logger = logging.getLogger("JARVIS.MemoryScorer")


class MemoryImportance:
    """Named importance constants for readability."""
    CRITICAL = 10   # API keys, "never do X", hard constraints
    HIGH     = 8    # User identity facts, strong preferences, project info
    MEDIUM   = 5    # Technical content, how-tos, general knowledge
    LOW      = 2    # Ordinary conversation turns
    NOISE    = 1    # "ok", "yes", "hi", empty acks


# ---------------------------------------------------------------------------
# Keyword tables
# ---------------------------------------------------------------------------

_CRITICAL_PATTERNS = [
    r"\bapi[_\s]?key\b", r"\bpassword\b", r"\btoken\b", r"\bsecret\b",
    r"\bnever\b.{0,30}\bagain\b", r"\balways\b.{0,30}\bdo\b",
    r"\bdo not\b.{0,30}\bever\b", r"\bimportant\b.{0,10}\bnote\b",
]

_HIGH_PATTERNS = [
    r"\bi (?:am|use|prefer|like|love|hate|need|want|always|usually)\b",
    r"\bmy (?:name|project|stack|framework|language|preference|goal|os|setup|editor|workflow)\b",
    r"\buser (?:is|uses|prefers|likes|builds|works on)\b",
    r"\bremember (?:that|this|me)\b",
    r"\bproject[:\s]+\w+",
    r"\bframework[:\s]+\w+",
    r"\bstack[:\s]+\w+",
    r"\bprefer\b",
]

_MEDIUM_PATTERNS = [
    r"\bhow to\b", r"\bsteps?\b", r"\btutorial\b", r"\bguide\b",
    r"\bexplain\b", r"\bdocument\b", r"\binstall\b", r"\bsetup\b",
    r"\bconfigure\b", r"\bdeploy\b", r"\bdebug\b", r"\bfix\b",
    r"\bcode\b", r"\bfunction\b", r"\bclass\b", r"\bmodule\b",
    r"\berror\b", r"\bbug\b", r"\bexception\b",
]

_NOISE_PATTERNS = [
    r"^(ok|okay|yes|no|sure|thanks|thank you|got it|alright|yep|nope|hmm)\.?$",
    r"^(hi|hello|hey|bye|goodbye|see you)\.?$",
]

# Tags mapped to domain keywords
_TAG_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("react",      ["react", "reactjs", "jsx", "hooks", "redux", "vite"]),
    ("python",     ["python", "pip", "django", "flask", "fastapi", "asyncio"]),
    ("selenium",   ["selenium", "webdriver", "browser automation", "chromedriver"]),
    ("jarvis",     ["jarvis", "voice assistant", "livekit", "agent"]),
    ("nova",       ["nova", "nova.ai"]),
    ("windows",    ["windows", "win32", "powershell", "cmd", "registry"]),
    ("git",        ["git", "github", "commit", "branch", "merge", "pull request"]),
    ("docker",     ["docker", "container", "kubernetes", "k8s", "compose"]),
    ("database",   ["sqlite", "postgres", "mysql", "mongodb", "redis", "chromadb"]),
    ("llm",        ["llm", "gpt", "gemini", "claude", "openai", "anthropic", "prompt"]),
    ("automation", ["automate", "automation", "script", "scheduled", "cron"]),
    ("testing",    ["test", "pytest", "unittest", "assert", "mock", "fixture"]),
    ("ui",         ["ui", "frontend", "css", "html", "tailwind", "design"]),
    ("api",        ["api", "rest", "graphql", "endpoint", "request", "response"]),
]

# Project detection: order matters (most specific first)
_PROJECT_PATTERNS: List[Tuple[str, List[str]]] = [
    ("jarvis",  ["jarvis", "j.a.r.v.i.s", "voice assistant", "livekit agent"]),
    ("nova",    ["nova.ai", "nova ai", "nova project"]),
    ("react",   ["react project", "react app", "reactjs project"]),
    ("python",  ["python project", "python script", "python module"]),
]


class MemoryScorer:
    """
    Rule-based memory classifier.  No LLM required — deterministic and fast.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, content: str, role: str = "user") -> int:
        """Return importance score 1–10 for this memory entry."""
        text = content.lower().strip()

        # Assistant acknowledgements are always noise
        if role == "assistant" and len(text) < 60:
            if re.match(r"^(sure|ok|yes|understood|got it|alright|noted)", text):
                return MemoryImportance.NOISE

        # Empty / very short
        if len(text) < 4:
            return MemoryImportance.NOISE

        # Noise check
        for pattern in _NOISE_PATTERNS:
            if re.fullmatch(pattern, text, re.IGNORECASE):
                return MemoryImportance.NOISE

        # Critical
        for pattern in _CRITICAL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return MemoryImportance.CRITICAL

        # High
        for pattern in _HIGH_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return MemoryImportance.HIGH

        # Medium
        medium_hits = sum(
            1 for p in _MEDIUM_PATTERNS if re.search(p, text, re.IGNORECASE)
        )
        if medium_hits >= 2:
            return MemoryImportance.MEDIUM

        # Low (ordinary conversation)
        if len(text) > 30:
            return MemoryImportance.LOW

        return MemoryImportance.NOISE

    def classify_type(self, content: str) -> str:
        """
        Classify into one of four memory types:
          semantic    — facts/preferences about user, world, or projects
          episodic    — past events and experiences
          procedural  — how-to knowledge and skills
          working     — temporary, in-context state
        """
        text = content.lower()

        # Procedural: how-to, steps, guide
        if re.search(r"\bhow to\b|\bsteps?\b|\bguide\b|\btutorial\b|\bprocess\b|\bworkflow\b", text):
            return "procedural"

        # Episodic: past-tense events
        if re.search(
            r"\byesterday\b|\blast week\b|\blast month\b|\bpreviously\b"
            r"|\bi (fixed|built|created|completed|finished|solved|deployed)\b"
            r"|\bused to\b|\bonce\b|\bhistory\b",
            text
        ):
            return "episodic"

        # Working memory: current state signals
        if re.search(
            r"\bcurrent(ly)?\b|\bright now\b|\btoday\b|\bthis session\b"
            r"|\bactive\b|\bopen tab\b|\bclipboard\b|\bplanning\b",
            text
        ):
            return "working"

        # Default: semantic
        return "semantic"

    def extract_tags(self, content: str) -> List[str]:
        """Return a list of domain-relevant tags found in content."""
        text = content.lower()
        tags = []
        for tag, keywords in _TAG_KEYWORDS:
            for kw in keywords:
                if kw in text:
                    tags.append(tag)
                    break
        return list(dict.fromkeys(tags))  # deduplicated, order preserved

    def detect_project(self, content: str) -> str:
        """Return the most likely project namespace for this content."""
        text = content.lower()
        for project, keywords in _PROJECT_PATTERNS:
            for kw in keywords:
                if kw in text:
                    return project
        return "general"

    def analyze(self, content: str, role: str = "user") -> dict:
        """
        Convenience method: run all classifiers and return a metadata dict
        ready to be stored in ChromaDB or SQLite.
        """
        importance   = self.score(content, role)
        memory_type  = self.classify_type(content)
        tags         = self.extract_tags(content)
        project      = self.detect_project(content)

        return {
            "importance":   importance,
            "memory_type":  memory_type,
            "tags":         ",".join(tags),      # stored as CSV string
            "project":      project,
        }
