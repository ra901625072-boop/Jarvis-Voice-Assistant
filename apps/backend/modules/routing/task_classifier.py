"""
modules.routing.task_classifier
--------------------------------
Unified Task Complexity Classification & Adaptive Routing Engine for JARVIS.

Categorizes user requests across a 6-level complexity spectrum (Level 0 - Level 5),
computes a quantitative Task Complexity Score (TCS: 0.0 to 1.0), and determines whether
the request follows the Express Low-Latency Lane or the Deep Multi-Agent Swarm Lane.
"""

import re
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger("JARVIS.TaskClassifier")


class TaskComplexityLevel(str, Enum):
    LEVEL_0_CONVERSATIONAL = "level_0_conversational"       # Greetings, small talk, identity, general Q&A
    LEVEL_1_MEMORY = "level_1_memory"                       # Personal facts, preferences, session history
    LEVEL_2_SINGLE_ACTION = "level_2_single_action"         # 1 atomic tool call (volume, screenshot, open app)
    LEVEL_3_MULTISTEP_DOMAIN = "level_3_multistep_domain"   # 2-4 steps within 1 specialist domain
    LEVEL_4_MULTI_AGENT_SWARM = "level_4_multi_agent_swarm" # Cross-specialist swarm orchestration
    LEVEL_5_DEEP_PROJECT = "level_5_deep_project"           # Autonomous coding, full apps, grounded UI workflows


class TaskExecutionLane(str, Enum):
    EXPRESS_CHAT = "express_chat"                 # Direct LLM generation / speech
    EXPRESS_MEMORY = "express_memory"             # Read-only memory retrieval + direct synthesis
    EXPRESS_TOOL = "express_tool"                 # Immediate single-tool dispatch
    STANDARD_DAG = "standard_dag"                 # Lightweight DAGScheduler execution
    SWARM_ORCHESTRATION = "swarm_orchestration"   # Full Coordinator -> Planner -> Executor -> Verifier loop
    GROUNDED_PROJECT = "grounded_project"         # Vision-in-the-loop / autonomous project pipeline


@dataclass
class TaskClassificationReport:
    query: str
    complexity_score: float
    complexity_level: TaskComplexityLevel
    is_complex: bool
    is_direct_chat: bool
    execution_lane: TaskExecutionLane
    primary_intent: str
    suggested_tool: Optional[str] = None
    extracted_params: Dict[str, Any] = field(default_factory=dict)
    target_agents: List[str] = field(default_factory=list)
    sub_goals: List[str] = field(default_factory=list)
    requires_grounded_vision: bool = False
    requires_verification: bool = False
    risk_level: str = "low"  # low, medium, high
    fast_subtasks: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "complexity_score": round(self.complexity_score, 3),
            "complexity_level": self.complexity_level.value,
            "is_complex": self.is_complex,
            "is_direct_chat": self.is_direct_chat,
            "execution_lane": self.execution_lane.value,
            "primary_intent": self.primary_intent,
            "suggested_tool": self.suggested_tool,
            "extracted_params": self.extracted_params,
            "target_agents": self.target_agents,
            "sub_goals": self.sub_goals,
            "requires_grounded_vision": self.requires_grounded_vision,
            "requires_verification": self.requires_verification,
            "risk_level": self.risk_level,
            "fast_subtasks_count": len(self.fast_subtasks) if self.fast_subtasks else 0,
        }


class TaskClassifier:
    """
    High-accuracy, sub-millisecond Task Complexity & Routing Engine.
    Combines compiled regexes, lexical entity extractors, and heuristic scoring.
    """

    # Complexity threshold separating Normal (Express Lane) from Complex (Swarm Lane)
    COMPLEXITY_THRESHOLD = 0.35

    # ── Level 0: Conversational & Q&A Patterns ────────────────────────────────
    GREETINGS_PATTERN = re.compile(
        r"^(?:hello|hi|hey|good\s+(?:morning|afternoon|evening|night)|namaste|salaam|ola|sup|yo)\b",
        re.IGNORECASE,
    )
    CHIT_CHAT_PATTERN = re.compile(
        r"\b(?:who\s+are\s+you|what\s+is\s+your\s+name|who\s+made\s+you|who\s+created\s+you|"
        r"how\s+are\s+you|how\s+r\s+u|how\s+do\s+you\s+do|kya\s+haal\s+hai|kaise\s+ho|tum\s+kaun\s+ho|"
        r"thank\s+you|thanks|thank\s+u|dhanyawad|shukriya|bye|goodbye|see\s+you|cya|"
        r"what\s+can\s+you\s+do|what\s+are\s+your\s+capabilities|help|kya\s+kar\s+sakte\s+ho|"
        r"are\s+you\s+there|are\s+you\s+online|systems\s+status|status\s+check)\b",
        re.IGNORECASE,
    )
    QA_PREFIX_PATTERNS = [
        re.compile(r"^(?:what\s+is|what\s+are|what\s+was|what\s+were)\s+(?!the\s+file|the\s+output|the\s+error)", re.IGNORECASE),
        re.compile(r"^(?:how\s+does|how\s+do|how\s+can\s+one|how\s+to\s+explain)", re.IGNORECASE),
        re.compile(r"^(?:why\s+is|why\s+are|why\s+does|why\s+do)", re.IGNORECASE),
        re.compile(r"^(?:who\s+was|who\s+is|who\s+won|who\s+discovered)", re.IGNORECASE),
        re.compile(r"^(?:explain|describe|define|summarize|tell\s+me\s+about|calculate|what\s+is\s+\d+)", re.IGNORECASE),
        re.compile(r"^(?:write\s+(?:a\s+)?(?:short\s+)?(?:poem|story|joke|essay|quote|riddle|haiku))", re.IGNORECASE),
    ]

    # ── Level 1: Personal Memory Patterns ─────────────────────────────────────
    MEMORY_QUERY_PATTERNS = [
        re.compile(r"\b(?:what\s+(?:is|do)\s+you\s+know\s+about\s+me)\b", re.IGNORECASE),
        re.compile(r"\b(?:what\s+do\s+you\s+remember|do\s+you\s+remember)\b", re.IGNORECASE),
        re.compile(r"\b(?:who\s+am\s+i|what\s+is\s+my\s+name|do\s+you\s+know\s+me)\b", re.IGNORECASE),
        re.compile(r"\b(?:what\s+(?:did\s+we|were\s+we)\s+(?:discuss|discussing|talk\s+about|talking\s+about|do|doing|work\s+on|working\s+on))\b", re.IGNORECASE),
        re.compile(r"\b(?:what\s+are\s+my\s+preferences|my\s+profile\s+details)\b", re.IGNORECASE),
        re.compile(r"\b(?:tell\s+me\s+(?:everything\s+)?about\s+me)\b", re.IGNORECASE),
    ]

    # ── Level 5: Grounded Vision & Deep Coding Patterns ───────────────────────
    GROUNDED_VISION_PATTERNS = [
        re.compile(r'\b(?:click|tap|press|select|choose)\s+(?:on\s+)?(?:the\s+)?(?:1st|2nd|3rd|\d+th|first|second|third|fourth|last)\b', re.IGNORECASE),
        re.compile(r'\b(?:click|tap|press)\s+(?:on\s+)?(?:the\s+)?(?:button|icon|logo|menu|checkbox|radio|link)\b', re.IGNORECASE),
        re.compile(r'\b(?:scroll\s+until|inspect\s+(?:the\s+)?(?:chart|image|diagram|screen)|look\s+at\s+(?:the\s+)?screen)\b', re.IGNORECASE),
        re.compile(r'\b(?:select|choose)\s+(?:the\s+)?(?:biggest|cheapest|highest|lowest)\b', re.IGNORECASE),
    ]
    DEEP_PROJECT_PATTERNS = [
        re.compile(r'\b(?:build|create|develop|scaffold|code)\s+.*?\b(?:full\s*stack|app|website|project|platform|dashboard|microservice|backend|frontend)\b', re.IGNORECASE),
        re.compile(r'\b(?:refactor|rewrite|debug|diagnose|fix\s+all)\s+(?:the\s+)?(?:codebase|repo|module|architecture|pipeline|database)\b', re.IGNORECASE),
        re.compile(r'\b(?:research|investigate|conduct\s+deep\s+research)\s+.*?\s+(?:and\s+write|and\s+compile|and\s+save)\b', re.IGNORECASE),
    ]

    # High-risk / Destructive Operations
    RISK_PATTERNS = [
        re.compile(r'\b(?:delete|remove|rmdir|unlink|drop\s+database|format\s+drive|kill\s+process|shutdown|reboot)\b', re.IGNORECASE),
        re.compile(r'\b(?:overwrite|truncate|git\s+reset\s+--hard|git\s+clean\s+-fd)\b', re.IGNORECASE),
    ]

    @classmethod
    def decompose_intents(cls, text: str) -> List[str]:
        """
        Decomposes compound user requests containing 'and then', 'while', or multi-sentence instructions.
        """
        if not text or not text.strip():
            return []

        # Split on strong multi-task conjunctions, newlines, or sentence-ending periods (avoiding domain dots)
        parts = re.split(r'\b(?:and also|and then|while|in addition|after that)\b|\n+|\.\s+(?=[A-Z0-9])', text, flags=re.IGNORECASE)
        goals = [p.strip() for p in parts if p.strip() and len(p.strip()) > 3]

        return goals if goals else [text.strip()]

    @classmethod
    def classify(cls, query: str) -> TaskClassificationReport:
        """
        Classifies a user query string into a complete TaskClassificationReport.
        """
        if not query or not query.strip():
            return TaskClassificationReport(
                query="",
                complexity_score=0.0,
                complexity_level=TaskComplexityLevel.LEVEL_0_CONVERSATIONAL,
                is_complex=False,
                is_direct_chat=True,
                execution_lane=TaskExecutionLane.EXPRESS_CHAT,
                primary_intent="conversational",
                sub_goals=[],
            )

        q = query.strip()
        q_lower = q.lower()
        sub_goals = cls.decompose_intents(q)

        # ── 1. Check Exact Level 0: Greetings & Chit-Chat ─────────────────────
        if cls.GREETINGS_PATTERN.match(q) or cls.CHIT_CHAT_PATTERN.search(q):
            if not any(v in q_lower for v in ["create a file", "save to", "write to file", "run command", "and fix", "and build", "build ", "delete "]):
                return TaskClassificationReport(
                    query=q,
                    complexity_score=0.05,
                    complexity_level=TaskComplexityLevel.LEVEL_0_CONVERSATIONAL,
                    is_complex=False,
                    is_direct_chat=True,
                    execution_lane=TaskExecutionLane.EXPRESS_CHAT,
                    primary_intent="greetings_and_chitchat",
                    sub_goals=[q],
                )

        # ── 2. Check Level 1: Memory & Profile Queries ─────────────────────────
        for pattern in cls.MEMORY_QUERY_PATTERNS:
            if pattern.search(q_lower):
                return TaskClassificationReport(
                    query=q,
                    complexity_score=0.15,
                    complexity_level=TaskComplexityLevel.LEVEL_1_MEMORY,
                    is_complex=False,
                    is_direct_chat=True,
                    execution_lane=TaskExecutionLane.EXPRESS_MEMORY,
                    primary_intent="memory_inquiry",
                    target_agents=["memory_agent"],
                    sub_goals=[q],
                )

        # ── 3. Check Level 2: Atomic Deterministic Actions (Fast Path) ─────────
        if len(sub_goals) <= 1:
            fast_action = cls._check_atomic_system_actions(q, q_lower)
            if fast_action:
                tool_name, params, fast_subtasks, action_type = fast_action
                return TaskClassificationReport(
                    query=q,
                    complexity_score=0.25,
                    complexity_level=TaskComplexityLevel.LEVEL_2_SINGLE_ACTION,
                    is_complex=False,
                    is_direct_chat=False,
                    execution_lane=TaskExecutionLane.EXPRESS_TOOL,
                    primary_intent=action_type,
                    suggested_tool=tool_name,
                    extracted_params=params,
                    target_agents=["execution_agent"],
                    sub_goals=[q],
                    fast_subtasks=fast_subtasks,
                )

        # ── 4. Check Level 0: Informational Q&A ────────────────────────────────
        is_qa = False
        for qa_pat in cls.QA_PREFIX_PATTERNS:
            if qa_pat.search(q_lower):
                # Exclude operational overrides like "explain code in file.py and fix it", WhatsApp group/chat summaries, etc.
                operational_keywords = [
                    "create a file", "save to", "write to file", "run command", "and fix", "and build",
                    "whatsapp", "group", "grup", "chat", "inbox", "email", "gmail", "instagram", "dm", "dms",
                    "discussion", "messages", "message", "conversation", "channel", "thread", "unread", "contact"
                ]
                has_operational = any(v in q_lower for v in operational_keywords) or ('"' in q or "'" in q)
                if not has_operational:
                    is_qa = True
                    break
        if is_qa:
            return TaskClassificationReport(
                query=q,
                complexity_score=0.15,
                complexity_level=TaskComplexityLevel.LEVEL_0_CONVERSATIONAL,
                is_complex=False,
                is_direct_chat=True,
                execution_lane=TaskExecutionLane.EXPRESS_CHAT,
                primary_intent="informational_qa",
                sub_goals=[q],
            )

        # ── 5. Check Level 5: Grounded Vision & Deep Autonomous Projects ───────
        requires_vision = any(pat.search(q_lower) for pat in cls.GROUNDED_VISION_PATTERNS)
        is_deep_project = any(pat.search(q_lower) for pat in cls.DEEP_PROJECT_PATTERNS)

        # ── 6. Check High-Risk / Destructive Operations ────────────────────────
        is_high_risk = any(pat.search(q_lower) for pat in cls.RISK_PATTERNS)
        risk_level = "high" if is_high_risk else ("medium" if len(sub_goals) > 2 else "low")

        # ── 7. Calculate Quantitative Complexity Score (TCS) ──────────────────
        score = cls._compute_complexity_score(
            q_lower=q_lower,
            sub_goals=sub_goals,
            requires_vision=requires_vision,
            is_deep_project=is_deep_project,
            is_high_risk=is_high_risk,
        )

        is_complex = score > cls.COMPLEXITY_THRESHOLD

        # Map to Complexity Level & Target Agents
        if score >= 0.70 or is_deep_project or requires_vision:
            level = TaskComplexityLevel.LEVEL_5_DEEP_PROJECT
            lane = TaskExecutionLane.GROUNDED_PROJECT if requires_vision else TaskExecutionLane.SWARM_ORCHESTRATION
            target_agents = ["coordinator_agent", "planning_agent", "coding_agent", "verification_agent"]
            if requires_vision:
                target_agents.extend(["vision_agent", "interaction_agent"])
        elif score >= 0.50 or len(sub_goals) >= 3:
            level = TaskComplexityLevel.LEVEL_4_MULTI_AGENT_SWARM
            lane = TaskExecutionLane.SWARM_ORCHESTRATION
            target_agents = ["coordinator_agent", "planning_agent", "execution_agent", "verification_agent"]
        elif is_complex:
            level = TaskComplexityLevel.LEVEL_3_MULTISTEP_DOMAIN
            lane = TaskExecutionLane.STANDARD_DAG
            target_agents = ["coordinator_agent", "execution_agent"]
        else:
            # Check if there is any action verb
            action_verbs = [
                "create", "build", "make", "generate", "code", "open", "launch", "start", "run", "execute",
                "delete", "close", "set", "play", "search", "connect", "integrate", "link", "read", "check",
                "show", "get", "fetch", "list", "send", "inspect", "message", "massage", "whatsapp", "email",
                "gmail", "instagram", "unread"
            ]
            has_action = any(v in q_lower for v in action_verbs)
            if not has_action:
                level = TaskComplexityLevel.LEVEL_0_CONVERSATIONAL
                lane = TaskExecutionLane.EXPRESS_CHAT
                target_agents = []
                is_direct_chat = True
            else:
                level = TaskComplexityLevel.LEVEL_2_SINGLE_ACTION
                lane = TaskExecutionLane.EXPRESS_TOOL
                target_agents = ["execution_agent"]
                is_direct_chat = False

            return TaskClassificationReport(
                query=q,
                complexity_score=score,
                complexity_level=level,
                is_complex=False,
                is_direct_chat=is_direct_chat,
                execution_lane=lane,
                primary_intent="conversational" if is_direct_chat else "operational_action",
                target_agents=target_agents,
                sub_goals=sub_goals,
                requires_grounded_vision=False,
                requires_verification=is_high_risk,
                risk_level=risk_level,
            )

        return TaskClassificationReport(
            query=q,
            complexity_score=score,
            complexity_level=level,
            is_complex=is_complex,
            is_direct_chat=False,
            execution_lane=lane,
            primary_intent="complex_goal" if is_complex else "operational_action",
            target_agents=target_agents,
            sub_goals=sub_goals,
            requires_grounded_vision=requires_vision,
            requires_verification=(is_complex or is_high_risk),
            risk_level=risk_level,
        )

    @classmethod
    def _compute_complexity_score(
        cls,
        q_lower: str,
        sub_goals: List[str],
        requires_vision: bool,
        is_deep_project: bool,
        is_high_risk: bool,
    ) -> float:
        """
        Computes TCS = min(1.0, w_intent + w_clauses + w_verbs + w_entities + w_risk + w_visual)
        """
        score = 0.20  # Base operational action weight

        # Clause / Sub-goal penalty
        clause_count = len(sub_goals)
        if clause_count > 1:
            score += min(0.30, (clause_count - 1) * 0.15)

        # Action Verb Density
        action_verbs = [
            "create", "build", "make", "generate", "code", "refactor", "debug", "fix",
            "open", "launch", "start", "close", "kill", "stop", "restart",
            "run", "execute", "install", "download", "browse", "navigate", "search",
            "scrape", "extract", "click", "type", "press", "scroll", "delete",
            "analyze", "analyse", "compile", "summarize", "synthesize", "research",
            "investigate", "compare", "email", "send", "save", "write", "fetch", "query", "archive", "format"
        ]
        matched_verbs = [v for v in action_verbs if re.search(rf"\b{v}\b", q_lower)]
        if len(matched_verbs) >= 3:
            score += 0.25
        elif len(matched_verbs) == 2:
            score += 0.15
        elif len(matched_verbs) == 1:
            score += 0.05

        # Explicit File & Code Artifact Indicators
        code_artifact_triggers = [
            r"\b(?:file|files|script|repo|component|backend|frontend|server|api|database|test|pytest|html|react|python)\b",
            r"\b(?:npm|pip|git|docker|docker-compose|sqlite|postgres|report|markdown|table|csv|json|document)\b",
        ]
        if any(re.search(pat, q_lower) for pat in code_artifact_triggers):
            score += 0.20

        # Grounded Vision Weight
        if requires_vision:
            score += 0.30

        # Deep Project Weight
        if is_deep_project:
            score += 0.40

        # Destructive Risk Weight
        if is_high_risk:
            score += 0.25

        return min(1.0, score)

    @classmethod
    def _check_atomic_system_actions(cls, q: str, q_lower: str) -> Optional[Tuple[str, Dict[str, Any], List[Dict[str, Any]], str]]:
        """
        Detects single-step deterministic actions and constructs their fast-path subtask template.
        Returns: (tool_name, args, subtasks_list, action_type) or None.
        """
        # 1. System volume controls
        if re.match(r"^(?:mute|unmute)(?:\s+(?:system|audio|volume|sound))*(?:[!?,.]*)$", q_lower):
            if "unmute" in q_lower:
                subtasks = [{"id": 1, "description": "Unmute system audio", "tool_name": "unmute_audio", "args": {}}]
                return "unmute_audio", {}, subtasks, "volume_control"
            else:
                subtasks = [{"id": 1, "description": "Mute system audio", "tool_name": "mute_audio", "args": {}}]
                return "mute_audio", {}, subtasks, "volume_control"

        vol_match = re.match(r'^(?:set|change)?\s*(?:system\s+)?volume\s+(?:to\s+)?(\d+)%?$', q_lower)
        if vol_match:
            try:
                level = int(vol_match.group(1))
                if 0 <= level <= 100:
                    subtasks = [{"id": 1, "description": f"Set system volume to {level}%", "tool_name": "set_volume", "args": {"level": level}}]
                    return "set_volume", {"level": level}, subtasks, "volume_control"
            except ValueError:
                pass

        # 2. Display brightness
        bright_match = re.match(r'^(?:set|change)?\s*(?:display\s+)?brightness\s+(?:to\s+)?(\d+)%?$', q_lower)
        if bright_match:
            try:
                level = int(bright_match.group(1))
                if 0 <= level <= 100:
                    subtasks = [{"id": 1, "description": f"Set display brightness to {level}%", "tool_name": "set_brightness", "args": {"level": level}}]
                    return "set_brightness", {"level": level}, subtasks, "brightness_control"
            except ValueError:
                pass

        # 3. Take screenshot
        if q_lower in ("take screenshot", "screenshot", "capture screen", "take a screenshot"):
            subtasks = [{"id": 1, "description": "Take system screenshot", "tool_name": "take_screenshot", "args": {}}]
            return "take_screenshot", {}, subtasks, "screenshot"

        # 4. Open Settings
        if q_lower in ("open settings", "launch settings", "settings", "open settings app", "settings app"):
            subtasks = [{"id": 1, "description": "Open system settings", "tool_name": "open_settings", "args": {}}]
            return "open_settings", {}, subtasks, "open_settings"

        # 5. Open Web URLs
        # Clean trailing phrases like "in browser", "in broswer", "in edge", "in chrome", "in new tab"
        cleaned_url_query = re.sub(r'\s+(?:in|on)\s+(?:browser|broswer|edge|chrome|new\s+tab|tab)$', '', q_lower).strip()

        url_match = re.match(r'^(?:open|visit|go\s+to|launch|show|browse)\s+(https?://[^\s]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?::\d+)?(?:/[^\s]*)?)$', cleaned_url_query)
        if not url_match:
            # Fallback search for domain inside open/visit prompt
            domain_match = re.search(r'\b(https?://[^\s]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?::\d+)?(?:/[^\s]*)?)\b', q_lower)
            if domain_match and any(q_lower.startswith(prefix) for prefix in ("open ", "visit ", "go to ", "launch ", "browse ", "show ")):
                if not any(w in q_lower for w in ["build", "create", "scaffold", "develop", "code", "repo"]):
                    url_match = domain_match

        if url_match:
            url_str = url_match.group(1).strip()
            if url_str in ("google", "google.com"):
                url = "https://www.google.com"
            elif url_str in ("youtube", "youtube.com"):
                url = "https://www.youtube.com"
            elif url_str in ("github", "github.com"):
                url = "https://github.com"
            elif url_str in ("wikipedia", "wikipedia.org"):
                url = "https://www.wikipedia.org"
            else:
                url = url_str if url_str.startswith(("http://", "https://")) else f"https://{url_str}"

            subtasks = [{
                "id": 1,
                "description": f"Open URL: {url}",
                "tool_name": "open_url",
                "args": {"url": url},
                "verify_condition_type": "url_reachable",
                "verify_target": url
            }]
            return "open_url", {"url": url}, subtasks, "open_url"

        # Simple name-only URLs (e.g. "open google", "open youtube", "open github")
        for name, url in [("google", "https://www.google.com"), 
                          ("youtube", "https://www.youtube.com"), 
                          ("github", "https://github.com"), 
                          ("wikipedia", "https://www.wikipedia.org")]:
            if q_lower == f"open {name}":
                subtasks = [{
                    "id": 1,
                    "description": f"Open URL: {url}",
                    "tool_name": "open_url",
                    "args": {"url": url},
                    "verify_condition_type": "url_reachable",
                    "verify_target": url
                }]
                return "open_url", {"url": url}, subtasks, "open_url"

        # 6. YouTube video playback
        yt_match = re.match(r'^(?:play|watch)\s+(.+)\s+on\s+youtube$', q_lower)
        if not yt_match:
            yt_match = re.match(r'^(?:play|watch)\s+youtube\s+for\s+(.+)$', q_lower)
        if not yt_match:
            yt_match = re.match(r'^youtube\s+(?:play|watch)\s+(.+)$', q_lower)
        if yt_match:
            query_val = yt_match.group(1).strip()
            subtasks = [{
                "id": 1,
                "description": f"Play YouTube video for: {query_val}",
                "tool_name": "play_youtube",
                "args": {"query": query_val}
            }]
            return "play_youtube", {"query": query_val}, subtasks, "play_youtube"

        # 7. Search Google
        search_match = re.match(r'^(?:search\s+google\s+for|search\s+for|google)\s+(.+)$', q_lower)
        if not search_match:
            search_match = re.match(r'^(?:open\s+(?:the\s+)?browser\s+and\s+)?search\s+(?:for\s+)?(.+?)(?:\s+(?:on|in)\s+(?:the\s+)?browser)?$', q_lower)
        if search_match:
            query_val = search_match.group(1).strip()
            # Clean trailing/leading phrases
            query_val = re.sub(r'^(?:for\s+)', '', query_val).strip()
            query_val = re.sub(r'\s+(?:on|in)\s+(?:the\s+)?browser$', '', query_val).strip()
            if query_val and not any(w in query_val for w in [" and then ", " download", " extract", " compile", " save ", " create ", " write ", " summarize", " table "]):
                subtasks = [{
                    "id": 1,
                    "description": f"Search Google for: {query_val}",
                    "tool_name": "search_google",
                    "args": {"query": query_val}
                }]
                return "search_google", {"query": query_val}, subtasks, "search_google"

        # 8. Open Application (e.g. "open notepad", "open chrome", "launch calculator", "open browser")
        app_match = re.match(r'^(?:open|launch|start|run)\s+([a-zA-Z0-9\s_-]+)$', q_lower)
        if app_match:
            app_name = app_match.group(1).strip()
            if app_name.startswith("the "):
                app_name = app_name[4:].strip()
            # Do not hijack chat / messaging / social media requests
            if not any(w in app_name for w in ["and", "then", "after", "search", "file", "project", "script", "chat", "conversation", "message", "dm", "with", "of"]):
                if app_name in ("google chrome", "chrome browser"):
                    app_name = "chrome"
                elif app_name in ("command prompt", "cmd prompt"):
                    app_name = "cmd"
                elif app_name in ("ms edge", "microsoft edge"):
                    app_name = "edge"
                elif app_name in ("browser", "web browser", "internet", "default browser"):
                    app_name = "browser"

                subtasks = [{
                    "id": 1,
                    "description": f"Open {app_name}",
                    "tool_name": "open_application",
                    "args": {"app_name": app_name},
                    "verify_condition_type": "process_running",
                    "verify_target": app_name
                }]
                return "open_application", {"app_name": app_name}, subtasks, "open_app"

        # 9. Social Media & Communication Fast Paths
        # Open Chat / Direct Messaging Fast Path (WhatsApp, Instagram, LinkedIn)
        chat_match = re.match(
            r'^(?:open|launch|show)\s+(?:the\s+)?(?:whatsapp|instagram|linkedin)?\s*(?:chat|conversation|dm|messages?)\s+(?:with|of|for|to)\s+(.+)$',
            q_lower
        )
        if not chat_match:
            chat_match = re.match(
                r'^(?:open|launch|show)\s+(whatsapp|instagram|linkedin)\s+(?:chat|conversation|dm|messages?)\s*(?:with|of|for|to)?\s*(.*)$',
                q_lower
            )

        if chat_match:
            raw_contact = chat_match.group(1).strip()
            platform = "whatsapp"
            if "instagram" in q_lower:
                platform = "instagram"
            elif "linkedin" in q_lower:
                platform = "linkedin"

            clean_contact = re.sub(r'^(?:with|of|for|to)\s+', '', raw_contact, flags=re.IGNORECASE).strip()
            if clean_contact.lower() in ("whatsapp", "instagram", "linkedin", "chat", "conversation", "dm", "messages"):
                clean_contact = ""

            subtasks = [{
                "id": 1,
                "description": f"Open {platform.title()} chat with {clean_contact or 'contact'}",
                "tool_name": "open_chat_in_browser",
                "args": {"platform": platform, "contact": clean_contact}
            }]
            return "open_chat_in_browser", {"platform": platform, "contact": clean_contact}, subtasks, "open_chat_in_browser"

        # WhatsApp / Social Chat & Group Discussion Summarization Fast Path
        sum_match = re.match(
            r'^(?:summarize|summary\s+of|give\s+me\s+a\s+summary\s+of)\s+(?:the\s+)?(?:recent\s+)?(?:discussion|conversation|chat|messages?|thread)\s+(?:in|of|from|with|for)\s+(?:the\s+)?(?:whatsapp\s+)?(?:group\s+|grup\s+|chat\s+|channel\s+)?["\']?([^"\']+)["\']?$',
            q_lower
        )
        if not sum_match:
            sum_match = re.match(
                r'^(?:summarize|summary\s+of)\s+(?:the\s+)?(?:whatsapp\s+)?(?:group\s+|grup\s+|chat\s+)?["\']?([^"\']+)["\']?\s+(?:discussion|conversation|chat|messages?|thread)$',
                q_lower
            )
        if not sum_match:
            sum_match = re.match(
                r'^(?:summarize|summary\s+of)\s+(?:the\s+)?(?:recent\s+)?(?:whatsapp\s+)?(?:in\s+)?["\']([^"\']+)["\'](?:\s+(?:discussion|conversation|chat|messages?))?$',
                q_lower
            )

        if sum_match:
            target_contact = sum_match.group(1).strip().strip('"').strip("'")
            if target_contact and target_contact.lower() not in ("whatsapp", "chat", "messages", "inbox", "unread", "everything", "all"):
                subtasks = [{
                    "id": 1,
                    "description": f"Summarize WhatsApp conversation in {target_contact}",
                    "tool_name": "summarize_whatsapp_conversation",
                    "args": {"contact": target_contact, "limit": 30}
                }]
                return "summarize_whatsapp_conversation", {"contact": target_contact, "limit": 30}, subtasks, "social_media_summarize"

        # WhatsApp unread/messages regex match
        if re.search(r'\b(?:whatsapp|wa)\b', q_lower) and any(w in q_lower for w in ["unread", "message", "massage", "msg", "chat", "who", "check", "read", "tell"]):
            if not any(w in q_lower for w in ["send", "write", "reply", "forward", "post"]):
                subtasks = [{
                    "id": 1,
                    "description": "Retrieve unread messages from WhatsApp",
                    "tool_name": "read_social_messages",
                    "args": {"platform": "whatsapp", "contact": "", "filter": "unread"}
                }]
                return "read_social_messages", {"platform": "whatsapp", "contact": "", "filter": "unread"}, subtasks, "social_media_read"

        # Gmail unread/emails regex match
        if re.search(r'\b(?:gmail|email|emails|mail)\b', q_lower) and any(w in q_lower for w in ["unread", "inbox", "who", "check", "read", "tell", "recent", "new"]):
            if not any(w in q_lower for w in ["send", "write", "reply", "forward", "draft"]):
                subtasks = [{
                    "id": 1,
                    "description": "Retrieve unread emails from Gmail",
                    "tool_name": "read_social_messages",
                    "args": {"platform": "gmail", "contact": "", "filter": "unread"}
                }]
                return "read_social_messages", {"platform": "gmail", "contact": "", "filter": "unread"}, subtasks, "social_media_read"

        # Instagram unread/DMs regex match
        if re.search(r'\b(?:instagram|ig|insta)\b', q_lower) and any(w in q_lower for w in ["unread", "dm", "dms", "message", "massage", "who", "check", "read"]):
            if not any(w in q_lower for w in ["send", "write", "reply", "post", "comment"]):
                subtasks = [{
                    "id": 1,
                    "description": "Retrieve unread messages from Instagram",
                    "tool_name": "read_social_messages",
                    "args": {"platform": "instagram", "contact": "", "filter": "unread"}
                }]
                return "read_social_messages", {"platform": "instagram", "contact": "", "filter": "unread"}, subtasks, "social_media_read"

        if q_lower in ("what is my social media status", "check social media status", "social media status", "check my social media", "social status"):
            subtasks = [{
                "id": 1,
                "description": "Check social media connection status",
                "tool_name": "get_social_status",
                "args": {}
            }]
            return "get_social_status", {}, subtasks, "social_media_status"

        connect_match = re.match(
            r'^(?:jarvis\s+)?connect\s+(?:with\s+|to\s+)?(whatsapp|instagram|gmail|linkedin)(?:\s+account)?$',
            q_lower
        )
        if connect_match:
            platform = connect_match.group(1).lower()
            subtasks = [{
                "id": 1,
                "description": f"Connect social platform: {platform}",
                "tool_name": "connect_social_account",
                "args": {"platform": platform}
            }]
            return "connect_social_account", {"platform": platform}, subtasks, "social_connection"

        return None
