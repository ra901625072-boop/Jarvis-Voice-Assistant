"""
memory_lifecycle.py
-------------------
The central brain of the JARVIS memory system.

Purpose
-------
Orchestrates the complete memory lifecycle, replacing scattered nightly
calls with a single clean pipeline:

  Observe  →  Gate  →  Resolve  →  Store
      ↓
  Consolidate  →  Reflect  →  Replay  →  Decay
      ↓
  Merge  →  Goal Update  →  Retrieve

This module:
1. Wraps the real-time path (on_new_message)
2. Orchestrates the nightly maintenance batch (run_nightly)
3. Provides a context budget manager for LLM context trimming
4. Manages the agent self-model table

Context Budget Manager
----------------------
Prevents context overflow in the LLM prompt.
Default budget: 3000 tokens (~12,000 characters).
Trims context by prioritising: goals > semantic memories > reflections > other.
"""

import os
import logging
from datetime import datetime, date
from typing import List, Dict, Any, Optional

from modules.core.memory_gate import MemoryGate
from modules.core.conflict_resolver import ConflictResolver
from modules.core.experience_replay import ExperienceReplay
from modules.core.goal_memory import GoalMemory
from modules.core.tool_memory import ToolMemory
from modules.core.memory_consolidator import MemoryConsolidator
from modules.core.reflection_engine import ReflectionEngine

logger = logging.getLogger("JARVIS.MemoryLifecycle")

# Token-based context budget mapping (dynamic detection of token/character environments)
_raw_budget = int(os.getenv("JARVIS_CONTEXT_BUDGET", "3000"))
if _raw_budget > 6000:
    _CONTEXT_BUDGET_TOKENS = _raw_budget // 4
else:
    _CONTEXT_BUDGET_TOKENS = _raw_budget


# Cache tiktoken encoding at module level to avoid expensive re-import + re-creation on every call
try:
    import tiktoken as _tiktoken
    _TIKTOKEN_ENCODING = _tiktoken.get_encoding("cl100k_base")
except Exception:
    _TIKTOKEN_ENCODING = None


def _estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text block (approx 1 token = 4 characters)."""
    if _TIKTOKEN_ENCODING is not None:
        try:
            return len(_TIKTOKEN_ENCODING.encode(text))
        except Exception:
            pass
    return max(1, len(text) // 4)


def _trim_to_tokens(text: str, max_tokens: int) -> str:
    """Trim text to fit within max_tokens."""
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        tokens = encoding.encode(text)
        if len(tokens) <= max_tokens:
            return text
        return encoding.decode(tokens[:max_tokens]) + "\n[...trimmed]"
    except Exception:
        char_limit = max_tokens * 4
        if len(text) <= char_limit:
            return text
        return text[:char_limit] + "\n[...trimmed]"


class MemoryLifecycle:
    """
    MemoryLifecycle orchestrates the entire memory system lifecycle, scheduling maintenance pipelines and compiling context budgets.

    SYSTEM PROMPT:
    Instantiate and use MemoryLifecycle to log new messages, schedule nightly consolidation pipelines, or construct sized context budgets for LLM prompts.

    SHORT DESCRIPTION:
    Orchestrates the entire memory process lifecycle from gating and contradiction resolution to consolidations, experience replays, and context budgets.

    PROCESS:
    1. On new messages, runs gating check, contradiction checks, and commits to DB.
    2. Runs nightly maintenance (consolidations, daily reflection, experience replayer, merge checks, auto goal checks).
    3. Builds sized context strings matching token budget priorities: goals > preferences > reminders > ranked memories > knowledge graphs > lessons > reflections.
    4. Manages agent self-model capabilities references.

    FLOW:
    Caller -> on_new_message() / run_nightly() / build_context() -> memory subsystems -> consolidator / replayer / SQLite DB tables -> Caller
    """

    def __init__(self, memory_manager):
        self.mm    = memory_manager
        self._dbs  = memory_manager.dbs
        self._lock = memory_manager._lock

        # Subsystems initialized directly at load time (no lazy load)
        self.gate         = MemoryGate()
        self.resolver     = ConflictResolver(self.mm)
        self.replayer     = ExperienceReplay(self.mm)
        self.goal_memory  = GoalMemory(self.mm)
        self.tool_memory  = ToolMemory(self.mm)

    # ------------------------------------------------------------------ #
    # Real-time path: on_new_message                                       #
    # ------------------------------------------------------------------ #

    def on_new_message(
        self,
        content: str,
        role: str,
        importance: int,
        memory_type: str,
        project: str,
        tags: str,
        timestamp: str,
    ) -> bool:
        """
        Called from MemoryManager.log_conversation for every new message.

        Pipeline
        --------
        1. Gate: decide if content deserves long-term storage
        2. Resolve: check for contradictions with existing memories
        3. Store: write to typed table + ChromaDB

        Returns True if the content passed the gate and was stored.
        """
        # Fetch recent semantic memory contents for duplicate check (fast path)
        recent_contents = self._get_recent_semantic_contents()

        # 1. Gate decision
        decision, reason = self.gate.evaluate(content, role, importance, recent_contents)
        self._log_gate(content, decision, reason)

        if decision == "reject":
            return False

        # DEFER means "not yet" — do NOT store as long-term memory yet
        if decision == "defer":
            return False

        # 2. Conflict resolution (only for semantic memories from users)
        if memory_type == "semantic" and role == "user":
            importance = self.resolver.check_and_resolve(content, importance, project)

        # 3. Store — delegate back to MemoryManager's private method
        self.mm._store_typed_memory(
            content=content,
            memory_type=memory_type,
            project=project,
            importance=importance,
            tags=tags,
            timestamp=timestamp,
        )

        return True

    # ------------------------------------------------------------------ #
    # Nightly maintenance                                                  #
    # ------------------------------------------------------------------ #

    def run_nightly(self) -> None:
        """
        Full nightly maintenance pipeline (called at 03:05).

        Order matters:
        1. Consolidate raw conversations
        2. Run daily reflection
        3. Extract lessons from failures
        4. Conflict merge pass (final dedup)
        5. Auto-detect goals from recent memories
        6. Weekly reflection (Sundays)
        7. Monthly reflection (1st of month)
        8. Purge expired working memory
        9. Prune old consolidated conversations
        """
        logger.info("MemoryLifecycle: starting nightly maintenance pipeline...")

        try:
            # 1. Consolidate
            MemoryConsolidator(self.mm).run()
        except Exception as e:
            logger.error(f"Consolidation failed: {e}")

        try:
            # 2. Daily reflection
            engine = ReflectionEngine(self.mm)
            engine.run_daily()
        except Exception as e:
            logger.error(f"Daily reflection failed: {e}")

        try:
            # 3. Experience replay
            self.replayer.run()
        except Exception as e:
            logger.error(f"Experience replay failed: {e}")

        try:
            # 4. Conflict merge pass
            merged = self.resolver.merge_pass()
            if merged:
                logger.info(f"Merge pass removed {merged} duplicate memories.")
        except Exception as e:
            logger.error(f"Merge pass failed: {e}")

        try:
            # 5. Auto-detect goals
            self.goal_memory.auto_detect_goals()
        except Exception as e:
            logger.error(f"Goal auto-detection failed: {e}")

        try:
            # 6. Weekly reflection (Sundays)
            if date.today().weekday() == 6:
                ReflectionEngine(self.mm).run_weekly()
        except Exception as e:
            logger.error(f"Weekly reflection failed: {e}")

        try:
            # 7. Monthly reflection (1st of month)
            if date.today().day == 1:
                ReflectionEngine(self.mm).run_monthly()
        except Exception as e:
            logger.error(f"Monthly reflection failed: {e}")

        # 8. Purge expired working memory
        try:
            self.mm._purge_working_memory()
        except Exception as e:
            logger.error(f"Working memory purge failed: {e}")

        # 9. Prune old consolidated conversations
        try:
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=7)).isoformat()
            with self._lock:
                self._dbs["conversations"].execute(
                    "DELETE FROM conversations WHERE consolidated=1 AND timestamp<?",
                    (cutoff,),
                )
                self._dbs["conversations"].commit()
        except Exception as e:
            logger.error(f"Conversation prune failed: {e}")

        logger.info("MemoryLifecycle: nightly maintenance complete.")

    # ------------------------------------------------------------------ #
    # Context Budget Manager                                               #
    # ------------------------------------------------------------------ #

    def build_context(
        self,
        current_query: Optional[str] = None,
        budget: Optional[int] = None,
    ) -> str:
        """
        Build a context string for the LLM that fits within the token budget.

        Priority order (highest → lowest):
        1. Active goals
        2. User preferences (always include)
        3. Pending tasks & reminders
        4. Semantic memories (goal-aware, hybrid ranked)
        5. Knowledge graph context
        6. Lessons learned (relevant procedural memory)
        7. Agent reflections (recent)
        8. Conversation summaries
        """
        if budget is None:
            token_budget = _CONTEXT_BUDGET_TOKENS
        elif budget > 6000:
            token_budget = budget // 4
        else:
            token_budget = budget

        # FAST PATH: if no query and no preferences exist, return empty quickly
        prefs = self.mm.get_all_preferences()  # Cache result — used again below
        goals_str = self.goal_memory.goal_context_string()
        if not current_query and not prefs and not goals_str:
            return ""

        sections: List[Dict[str, Any]] = []

        # 1. Active goals
        if goals_str:
            sections.append({"priority": 10, "text": goals_str})

        # 2. User preferences (reuse already-fetched prefs — no second DB call)
        if prefs:
            pref_str = "--- USER PREFERENCES ---\n" + "\n".join(
                f"- {k}: {v}" for k, v in prefs.items()
            )
            sections.append({"priority": 9, "text": pref_str})

        # 3. Pending tasks & reminders
        with self._lock:
            t_rows = self._dbs["conversations"].execute(
                "SELECT description FROM tasks WHERE status='pending'"
            ).fetchall()
            r_rows = self._dbs["conversations"].execute(
                "SELECT title, due_time FROM reminders WHERE completed=0"
            ).fetchall()
        if t_rows or r_rows:
            task_str = "--- PENDING TASKS & REMINDERS ---\n"
            for t in t_rows:
                task_str += f"- Task: {t[0]}\n"
            for r in r_rows:
                task_str += f"- Reminder: {r[0]} (Due: {r[1]})\n"
            sections.append({"priority": 8, "text": task_str.strip()})

        # 4. Semantic memories (goal-aware hybrid search)
        if current_query:
            active_goals = self.goal_memory.get_active_goals()
            memories = self.mm.search_memories(current_query, limit=6)
            if memories:
                mem_str = "--- RELEVANT MEMORIES ---\n"
                for m in memories:
                    snippet = m["content"][:200].replace("\n", " ")
                    mem_str += (
                        f"[{m.get('memory_type','?')}][{m.get('project','?')}]"
                        f"[imp:{m.get('importance',5)}] {snippet}\n"
                    )
                sections.append({"priority": 7, "text": mem_str.strip()})

        # 5. Knowledge graph
        if current_query:
            kg = self.mm._build_kg_context(current_query)
            if kg:
                sections.append({"priority": 6, "text": f"--- KNOWLEDGE GRAPH ---\n{kg}"})

        # 6. Relevant lessons learned
        if current_query:
            lessons = self._get_relevant_lessons(current_query)
            if lessons:
                sections.append({"priority": 5, "text": f"--- LESSONS LEARNED ---\n{lessons}"})

        # 7. Recent reflections (last 3 days)
        reflections = self.mm.get_agent_reflections(days=3)
        if reflections:
            ref_str = "--- AGENT REFLECTIONS ---\n"
            for r in reflections[:2]:
                ref_str += f"- {r['reflection'][:200]}\n"
            sections.append({"priority": 4, "text": ref_str.strip()})

        # 8. Conversation summaries
        with self._lock:
            sum_rows = self._dbs["conversations"].execute(
                """SELECT summary FROM conversation_summaries
                   ORDER BY created_at DESC LIMIT 2"""
            ).fetchall()
        if sum_rows:
            sum_str = "--- RECENT SUMMARIES ---\n" + "\n".join(r[0][:200] for r in sum_rows)
            sections.append({"priority": 3, "text": sum_str})

        # Sort by priority and apply token budget
        sections.sort(key=lambda s: s["priority"], reverse=True)
        result_parts = []
        used_tokens = 0

        for section in sections:
            text = section["text"]
            section_tokens = _estimate_tokens(text)
            if used_tokens + section_tokens <= token_budget:
                result_parts.append(text)
                used_tokens += section_tokens
            else:
                remaining_tokens = token_budget - used_tokens
                if remaining_tokens > 25:
                    trimmed_text = _trim_to_tokens(text, remaining_tokens)
                    result_parts.append(trimmed_text)
                break

        return "\n\n".join(result_parts)

    # ------------------------------------------------------------------ #
    # Agent self-model                                                     #
    # ------------------------------------------------------------------ #

    def get_self_model_context(self) -> str:
        """Return a formatted string of JARVIS's self-known capabilities."""
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT capability, category, confidence, notes
                   FROM agent_self_model
                   ORDER BY category, confidence DESC
                   LIMIT 20"""
            ).fetchall()

        if not rows:
            return ""

        lines = ["--- AGENT SELF-MODEL ---"]
        current_cat = None
        for capability, category, confidence, notes in rows:
            if category != current_cat:
                lines.append(f"\n[{category.upper()}]")
                current_cat = category
            note_str = f" ({notes})" if notes else ""
            pct = round(confidence * 100)
            lines.append(f"  - {capability} [{pct}% confidence]{note_str}")
        return "\n".join(lines)

    def seed_self_model(self) -> None:
        """
        Seed the agent_self_model table with JARVIS's known capabilities
        (called once at startup if empty).
        """
        with self._lock:
            count = self._dbs["conversations"].execute(
                "SELECT COUNT(*) FROM agent_self_model"
            ).fetchone()[0]
            if count > 0:
                return

        ts = datetime.now().isoformat()
        capabilities = [
            ("Open and close applications",          "system",      1.0,  None),
            ("Control system volume and brightness", "system",      1.0,  None),
            ("Shutdown/restart/sleep the computer",  "system",      1.0,  "requires confirmation"),
            ("Minimize/maximize/focus windows",      "system",      1.0,  None),
            ("Type text and press keyboard keys",    "system",      1.0,  None),
            ("Move/click/scroll mouse",              "system",      1.0,  None),
            ("Open URLs in browser",                 "browser",     1.0,  None),
            ("Search Google and Wikipedia live",     "browser",     0.85, "may hit CAPTCHA with scraping"),
            ("Search and play YouTube videos",       "browser",     0.90, None),
            ("Switch browser tabs",                  "browser",     0.90, None),
            ("Read, create, copy, move files",       "filesystem",  1.0,  None),
            ("Search files and folders",             "filesystem",  1.0,  None),
            ("Capture and analyze screenshots",      "vision",      0.85, "requires Gemini Vision API"),
            ("Read text from screen (OCR)",          "vision",      0.80, "accuracy varies with font"),
            ("Find and click UI elements by description", "vision", 0.75, "best with clear descriptions"),
            ("Remember user preferences",            "memory",      1.0,  None),
            ("Search past conversations",            "memory",      1.0,  None),
            ("Plan and execute multi-step tasks",    "planning",    0.90, None),
            ("Run background tasks",                 "planning",    1.0,  None),
        ]

        with self._lock:
            for cap, cat, conf, notes in capabilities:
                self._dbs["conversations"].execute(
                    """INSERT OR IGNORE INTO agent_self_model
                       (capability, category, confidence, notes, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (cap, cat, conf, notes, ts),
                )
            self._dbs["conversations"].commit()
        logger.info(f"Agent self-model seeded with {len(capabilities)} capabilities.")

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _get_recent_semantic_contents(self) -> List[str]:
        """Fetch last 50 semantic memory contents for gate duplicate check."""
        try:
            with self._lock:
                rows = self._dbs["conversations"].execute(
                    "SELECT content FROM semantic_memories ORDER BY id DESC LIMIT 50"
                ).fetchall()
            return [r[0] for r in rows]
        except Exception:
            return []

    def _log_gate(self, content: str, decision: str, reason: str) -> None:
        """Log gate decision to gate_log table."""
        import hashlib
        ts          = datetime.now().isoformat()
        content_hash = hashlib.sha256(content.lower().encode()).hexdigest()[:16]
        try:
            with self._lock:
                self._dbs["conversations"].execute(
                    "INSERT INTO gate_log (content_hash, decision, reason, created_at) VALUES (?,?,?,?)",
                    (content_hash, decision, reason, ts),
                )
                # Don't commit here — lazy commit on next natural write
        except Exception as e:
            logger.debug(f"Gate log failed: {e}")

    def _get_relevant_lessons(self, query: str) -> str:
        """Fetch lessons relevant to the query from lessons_learned."""
        try:
            words = [w for w in query.lower().split() if len(w) > 3][:5]
            if not words:
                return ""
            like_clauses = " OR ".join("lesson LIKE ?" for _ in words)
            params = [f"%{w}%" for w in words]
            with self._lock:
                rows = self._dbs["conversations"].execute(
                    f"""SELECT lesson FROM lessons_learned
                        WHERE {like_clauses}
                        ORDER BY importance DESC, last_triggered DESC
                        LIMIT 3""",
                    params,
                ).fetchall()
            if not rows:
                return ""
            return "\n".join(f"- {r[0][:200]}" for r in rows)
        except Exception as e:
            logger.debug(f"Lesson lookup failed: {e}")
            return ""
