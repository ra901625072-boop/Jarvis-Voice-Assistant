# JARVIS Real-Time Agent Learning Plan
### Making the Architect (Supervisor) and every specialist agent learn after **every** task — not just at 03:05

---

## 1. Executive Summary

JARVIS already *records* every agent's task outcome in real time (`agent_task_outcomes` is written after every `_create_result()` call, fire-and-forget). What it does **not** do is *learn* from that outcome in real time. All the actual intelligence — success-rate computation, trend detection, capability scoring, lesson extraction, self-model updates — is batched into the 03:05 nightly job (`MemoryLifecycle.run_nightly`). A failure at 9:00 AM is invisible to every agent (including the Supervisor/architect that routes work) until the next night's batch runs, unless it's the *second consecutive* failure of the exact same `(agent_id, task_type)` pair — and even that check lives in a Python dict that is wiped on every process restart.

This plan closes that gap with a **two-speed learning loop**:

- **Fast loop (new):** fires after every single task, updates a live confidence signal, and immediately writes usable lessons/reflections when a real pattern emerges (2 in a row, persisted — not in-memory).
- **Slow loop (existing, kept):** the nightly batch still runs, recomputing ground-truth 30-day success rates, trends, decay, and merges. It becomes a *consolidator* of what the fast loop already surfaced, not the sole source of learning.

Because every one of the 12 agents — **including the Supervisor ("architect")** — inherits from `BaseAgent` and already funnels every result through `_create_result()`, the hook point is a **single change in one file** (`ai/agents/base_agent.py`). No per-agent code changes are required for coverage of routed work. There is one real gap specific to the architect, covered in §6.

---

## 2. Current State (grounded in the uploaded codebase)

| Stage | Where | Frequency | Scope |
|---|---|---|---|
| Outcome recorded | `BaseAgent.record_outcome()` → `agent_task_outcomes` | **Every task** (already real-time, fire-and-forget) | All agents |
| Failure streak counted | `ExperienceReplay._agent_failure_counts` (in-process `dict`) | Every failure | All agents, **lost on restart** |
| Full agent reflection | `AgentSelfReflector.run_for_agent()` | Nightly, **or** when in-memory streak hits 2 | Per agent, scans 30 days |
| Capability score | `AgentCapabilityTracker.run_nightly()` → `agent_capability_scores`, `agent_self_model` | **Nightly only** (`run_nightly`, called from `MemoryLifecycle.run_nightly` at 03:05) | All agents |
| Lesson extraction | `ExperienceReplay.run()` → `lessons_learned`, `procedural_memories` | **Nightly only**, plus the 2-in-a-row trigger above | Global (episodic/workflow/tool) |
| Lessons/reflections surfaced back to agents | `MemoryLifecycle.build_context()` reads `lessons_learned` + `agent_reflections` live from DB | Every prompt build (already real-time — it's just starved of fresh data) | All agents |

**Key finding:** `build_context()` is already real-time — it queries the DB on every call. The bottleneck is entirely on the *write* side. Fixing the write side automatically makes learning visible to every agent's next task, with no changes needed to context building.

### 2.1 Confirmed gaps

1. **No incremental capability score.** `agent_capability_scores` and the confidence-threshold-driven `agent_self_model` rows are only touched by `AgentCapabilityTracker.run_nightly()`. A brilliant or terrible run at 10 AM doesn't move the needle until the next night.
2. **Failure-streak counter is not persisted.** `ExperienceReplay._agent_failure_counts` is a plain dict on the `ExperienceReplay` instance. A process restart (very common during active development, per your recent audit-and-fix cycles) silently resets every agent's streak to zero, so the "2 failures in a row" real-time trigger under-fires in practice.
3. **Successes teach nothing in real time.** Only failures move the fast path at all, and even that's gated behind the reset-prone counter above. A string of successes doesn't reinforce confidence until the nightly job.
4. **The Supervisor/architect's real work is mostly invisible to the learning system.** `SupervisorAgent.handle()` only produces an `AgentResult` (and therefore only calls `record_outcome`) for the `"speak"` task type. Its actual architectural work — context retrieval routing, low-confidence verification hand-off, session reconnects — happens inline in `run_session()` and never goes through `_create_result()`. So the agent most responsible for routing decisions currently has the thinnest self-model of all 12 agents.
5. **Failure pattern extraction is duplicated** with slightly different keyword sets in `ExperienceReplay._extract_failure_pattern` and `AgentSelfReflector._extract_failure_clusters`, which will drift over time and makes the fast/slow paths disagree.

---

## 3. Target Architecture

```
                         ┌─────────────────────────────┐
   Any agent finishes    │        BaseAgent             │
   a task (incl.         │  _create_result()            │
   Supervisor/architect) │      └─ record_outcome()      │
                         └───────────┬──────────────────┘
                                     │ (background thread/task — non-blocking)
                                     ▼
                     ┌────────────────────────────────┐
                     │ 1. INSERT agent_task_outcomes   │   (unchanged, already exists)
                     └───────────┬────────────────────┘
                                     ▼
                     ┌────────────────────────────────┐
                     │  RealtimeLearner.process()  NEW  │
                     │  ── fast loop, fires every task ──│
                     │  a) EMA capability nudge          │
                     │  b) self-model threshold check    │
                     │  c) persisted failure streak       │
                     │  d) 2nd-in-a-row → instant lesson  │
                     │  e) micro-reflection row           │
                     └───────────┬────────────────────┘
                                     ▼
        immediately visible to  ┌────────────────────────────────┐
        next call to            │ agent_capability_scores          │
        build_context()         │ agent_self_model                 │
        (no code change needed) │ lessons_learned / procedural_mem │
                                 │ agent_reflections (period=rt)    │
                                 └───────────┬───────────────────┘
                                             │
                                             ▼
                     ┌────────────────────────────────────┐
   03:05 nightly      │  MemoryLifecycle.run_nightly()       │
   (existing, kept)   │  ── slow loop, ground truth ──        │
                       │  AgentSelfReflector (30-day rates)   │
                       │  AgentCapabilityTracker (last-50 avg)│
                       │  ExperienceReplay.run() (deep scan)  │
                       │  decay / merge / prune                │
                       └────────────────────────────────────┘
```

Design principle: the fast loop never *replaces* a ground-truth number, it only *nudges* it between nightly recomputations. The nightly job always overwrites with the true last-50-run average, so the two loops can never permanently diverge.

---

## 4. New/Modified Components

### 4.1 Schema additions (`modules/core/memory_manager.py`)

Add these right before the existing `conn.commit()` at the end of the schema block (same file already defines `agent_task_outcomes` and `agent_capability_scores`, and already has a `_safe_alter` helper used elsewhere for additive migrations):

```python
# --- Real-time learning: persisted failure streaks (replaces in-memory dict) ---
c.execute("""
    CREATE TABLE IF NOT EXISTS agent_failure_streaks (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id     TEXT NOT NULL,
        task_type    TEXT NOT NULL,
        streak       INTEGER DEFAULT 0,
        last_pattern TEXT,
        updated_at   TEXT NOT NULL,
        UNIQUE(agent_id, task_type)
    )
""")

# --- Real-time learning: EMA confidence nudge, separate from the nightly ground-truth score ---
_safe_alter(conn, "agent_capability_scores", "ema_score", "REAL DEFAULT 0.8")
_safe_alter(conn, "agent_capability_scores", "last_task_id", "TEXT")

conn.commit()
```

`_safe_alter` already exists in this file (used for `semantic_memories.superseded` etc.), so this follows the established migration pattern exactly — additive, idempotent, safe to run on an existing DB.

### 4.2 Shared failure-pattern extraction (`modules/core/failure_patterns.py` — new file)

Both `ExperienceReplay` and `AgentSelfReflector` currently maintain their own, slightly different keyword clustering. Consolidate into one module so the fast and slow loops always agree on what a "timeout" or "captcha" failure looks like:

```python
"""
failure_patterns.py
--------------------
Single source of truth for clustering error text into a canonical pattern key.
Used by both the real-time learner and the nightly ExperienceReplay/AgentSelfReflector
so fast-loop and slow-loop lesson keys never drift apart.
"""
import re
from typing import Optional

# (regex, canonical_key) — ordered, first match wins.
# Superset of the previous ExperienceReplay._extract_failure_pattern and
# AgentSelfReflector._extract_failure_clusters keyword sets.
_PATTERNS = [
    (r"captcha", "captcha_triggered"),
    (r"timeout|timed out", "request_timeout"),
    (r"selenium.*fail|fail.*selenium", "selenium_failure"),
    (r"blocked|rate.?limit", "rate_limited"),
    (r"not found|404", "resource_not_found"),
    (r"permission.?denied|access.?denied", "permission_denied"),
    (r"connection.?refused|connect.?error", "connection_error"),
    (r"crash|exception|traceback", "crash_or_exception"),
    (r"google.*fail|fail.*google", "google_search_failure"),
    (r"download.?fail|failed.?download", "download_failure"),
]


def extract_pattern(error_text: Optional[str]) -> str:
    """Return a canonical failure-pattern key, or 'general_failure' if nothing matches."""
    if not error_text:
        return "unclassified_failure"
    text = error_text.lower()
    for regex, key in _PATTERNS:
        if re.search(regex, text):
            return key
    return "general_failure"
```

Then update the two existing callers to delegate to this (small, low-risk diffs):

- `modules/core/experience_replay.py::_extract_failure_pattern` → `return failure_patterns.extract_pattern(content)`
- `modules/core/agent_self_reflector.py::_extract_failure_clusters` → use `failure_patterns.extract_pattern(err)` instead of its inline `if/elif` chain.

### 4.3 The fast loop itself (`modules/core/realtime_learner.py` — new file)

```python
"""
realtime_learner.py
--------------------
Fast-loop, per-task learning. Runs once immediately after every single agent
task outcome is recorded (success or failure) — for every agent, including
the Supervisor/architect.

This complements, and never replaces, the nightly ground-truth batch run by
AgentSelfReflector / AgentCapabilityTracker / ExperienceReplay. Those still
own the authoritative 30-day / last-50-run numbers; this module only nudges
a live confidence signal and reacts instantly to a repeated, persisted
failure pattern instead of waiting for the next 03:05 run.

Called from BaseAgent.record_outcome() in the same background thread that
already writes agent_task_outcomes — so it costs nothing on the response
critical path.
"""

import logging
from datetime import datetime
from typing import Optional

from modules.core import failure_patterns

logger = logging.getLogger("JARVIS.RealtimeLearner")

# EMA smoothing factor for the live confidence nudge. Higher = more reactive.
_EMA_ALPHA = 0.2
# Consecutive same-pattern failures (persisted, survives restarts) before
# we immediately promote a lesson instead of waiting for the nightly scan.
_MIN_STREAK_FOR_INSTANT_LESSON = 2
_HIGH_CONFIDENCE_THRESHOLD = 0.90
_LOW_CONFIDENCE_THRESHOLD = 0.60
_MIN_RUNS_FOR_LOW_FLAG = 3


class RealtimeLearner:
    def __init__(self, memory_manager):
        self.mm = memory_manager
        self._dbs = memory_manager.dbs
        self._lock = memory_manager._lock

    # ------------------------------------------------------------------ #
    # Entry point                                                          #
    # ------------------------------------------------------------------ #

    def process(
        self,
        agent_id: str,
        task_type: str,
        task_id: str,
        success: bool,
        error_summary: Optional[str],
        goal_hint: str,
        duration_ms: float,
    ) -> None:
        try:
            ema = self._update_ema_capability(agent_id, task_type, task_id, success)
            self._apply_self_model_threshold(agent_id, task_type, ema)

            if success:
                self._reset_streak(agent_id, task_type)
            else:
                self._handle_failure(agent_id, task_type, error_summary, goal_hint)

            self._write_micro_reflection(agent_id, task_type, success, ema, goal_hint)
        except Exception as e:
            # Never let learning break the agent pipeline.
            logger.error(f"RealtimeLearner failed for {agent_id}/{task_type}: {e}", exc_info=True)

    # ------------------------------------------------------------------ #
    # 1. Live EMA confidence nudge                                         #
    # ------------------------------------------------------------------ #

    def _update_ema_capability(self, agent_id: str, task_type: str, task_id: str, success: bool) -> float:
        """
        Nudge a live EMA score toward this outcome. Does NOT touch success_rate /
        total_runs — those stay owned by the nightly AgentCapabilityTracker so the
        ground-truth numbers are never skewed by the fast loop.
        """
        outcome = 1.0 if success else 0.0
        ts = datetime.now().isoformat()
        with self._lock:
            row = self._dbs["conversations"].execute(
                "SELECT id, ema_score FROM agent_capability_scores WHERE agent_id = ? AND task_type = ?",
                (agent_id, task_type),
            ).fetchone()

            if row:
                row_id, prev_ema = row
                prev_ema = prev_ema if prev_ema is not None else 0.8
                new_ema = round((1 - _EMA_ALPHA) * prev_ema + _EMA_ALPHA * outcome, 4)
                self._dbs["conversations"].execute(
                    "UPDATE agent_capability_scores SET ema_score = ?, last_task_id = ? WHERE id = ?",
                    (new_ema, task_id, row_id),
                )
            else:
                # No nightly row yet (brand new agent/task_type combo) — seed one.
                new_ema = round(0.8 * 0.8 + _EMA_ALPHA * outcome, 4)
                self._dbs["conversations"].execute(
                    """INSERT INTO agent_capability_scores
                       (agent_id, task_type, success_rate, total_runs, confidence, last_updated, ema_score, last_task_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (agent_id, task_type, outcome, 1, outcome, ts, new_ema, task_id),
                )
            self._dbs["conversations"].commit()
        return new_ema

    def _apply_self_model_threshold(self, agent_id: str, task_type: str, ema: float) -> None:
        """Same threshold logic AgentCapabilityTracker uses nightly, applied instantly on the live EMA."""
        ts = datetime.now().isoformat()
        capability = f"{agent_id}:{task_type}"
        if ema >= _HIGH_CONFIDENCE_THRESHOLD:
            note = "High live confidence (>90%, real-time)"
        elif ema < _LOW_CONFIDENCE_THRESHOLD:
            note = "Low live confidence (<60%, real-time)"
        else:
            return  # mid-range: let the nightly ground-truth pass own this capability's note

        with self._lock:
            self._dbs["conversations"].execute(
                """INSERT INTO agent_self_model (capability, category, confidence, notes, created_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(capability) DO UPDATE SET confidence=excluded.confidence, notes=excluded.notes, created_at=excluded.created_at""",
                (capability, agent_id, ema, note, ts),
            )
            self._dbs["conversations"].commit()

    # ------------------------------------------------------------------ #
    # 2. Persisted failure streak + instant lesson                        #
    # ------------------------------------------------------------------ #

    def _reset_streak(self, agent_id: str, task_type: str) -> None:
        ts = datetime.now().isoformat()
        with self._lock:
            self._dbs["conversations"].execute(
                """INSERT INTO agent_failure_streaks (agent_id, task_type, streak, last_pattern, updated_at)
                   VALUES (?, ?, 0, NULL, ?)
                   ON CONFLICT(agent_id, task_type) DO UPDATE SET streak=0, last_pattern=NULL, updated_at=excluded.updated_at""",
                (agent_id, task_type, ts),
            )
            self._dbs["conversations"].commit()

    def _handle_failure(self, agent_id: str, task_type: str, error_summary: Optional[str], goal_hint: str) -> None:
        pattern = failure_patterns.extract_pattern(error_summary)
        ts = datetime.now().isoformat()

        with self._lock:
            row = self._dbs["conversations"].execute(
                "SELECT streak, last_pattern FROM agent_failure_streaks WHERE agent_id = ? AND task_type = ?",
                (agent_id, task_type),
            ).fetchone()

            if row and row[1] == pattern:
                streak = row[0] + 1
            else:
                streak = 1  # different pattern than last time — restart the streak

            self._dbs["conversations"].execute(
                """INSERT INTO agent_failure_streaks (agent_id, task_type, streak, last_pattern, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(agent_id, task_type) DO UPDATE SET streak=excluded.streak, last_pattern=excluded.last_pattern, updated_at=excluded.updated_at""",
                (agent_id, task_type, streak, pattern, ts),
            )
            self._dbs["conversations"].commit()

        if streak >= _MIN_STREAK_FOR_INSTANT_LESSON:
            self._promote_instant_lesson(agent_id, task_type, pattern, streak, goal_hint)

    def _promote_instant_lesson(self, agent_id: str, task_type: str, pattern: str, streak: int, goal_hint: str) -> None:
        """
        Fires immediately on the Nth same-pattern failure in a row (persisted — survives
        restarts, unlike the old in-memory ExperienceReplay._agent_failure_counts).
        Reuses ExperienceReplay._store_lesson so it lands in the exact same
        lessons_learned / procedural_memories tables build_context() already reads.
        """
        lesson_text = (
            f"Agent '{agent_id}' failed '{task_type}' {streak} time(s) in a row due to: {pattern}"
            f"{f' (goal: {goal_hint})' if goal_hint else ''}. Try an alternative approach before retrying."
        )
        source_pattern = f"rt_{agent_id}_{task_type}_{pattern}"[:64]

        if hasattr(self.mm, "lifecycle") and hasattr(self.mm.lifecycle, "replayer"):
            is_new = self.mm.lifecycle.replayer._store_lesson(
                lesson=lesson_text,
                source_pattern=source_pattern,
                occurrence_count=streak,
                project="general",
            )
            if is_new:
                logger.info(f"RealtimeLearner: instant lesson stored for {agent_id}/{task_type} ({pattern})")

    # ------------------------------------------------------------------ #
    # 3. Micro-reflection — keeps agent_reflections fresh between nights   #
    # ------------------------------------------------------------------ #

    def _write_micro_reflection(self, agent_id: str, task_type: str, success: bool, ema: float, goal_hint: str) -> None:
        ts = datetime.now().isoformat()
        status = "succeeded" if success else "failed"
        text = f"[{agent_id}] '{task_type}' just {status} (live confidence: {round(ema * 100)}%)."
        if goal_hint:
            text += f" Goal: {goal_hint}"
        with self._lock:
            self._dbs["conversations"].execute(
                """INSERT INTO agent_reflections (reflection, period, created_at)
                   VALUES (?, ?, ?)""",
                (text, "realtime", ts),
            )
            self._dbs["conversations"].commit()
```

Notes on design choices baked into this file:

- **EMA is a separate column (`ema_score`), never overwrites `success_rate`/`total_runs`.** Those two remain exclusively owned by `AgentCapabilityTracker.run_nightly()`, so there is no risk of the fast loop's smaller sample size corrupting the ground-truth 50-run average. `build_context()` and any future caller can choose the fast (`ema_score`) or ground-truth (`success_rate`) number depending on how fresh vs. how statistically solid they need it.
- **Streaks are pattern-aware, not just count-aware.** A timeout followed by a permission error no longer falsely counts as "2 in a row" — the streak resets when the pattern changes, exactly fixing the crude counting `ExperienceReplay._agent_failure_counts` did before.
- **Reuses `ExperienceReplay._store_lesson`** rather than duplicating lesson-writing logic — one lesson-writing code path, whether triggered instantly or by the nightly deep scan.
- **`period='realtime'`** on the reflection rows lets you distinguish fast-loop noise from nightly `agent_daily` reflections in the DB if you ever want to prune/weight them differently — `get_agent_reflections(days=3)` (used by `build_context`) already pulls both indiscriminately, which is the desired behavior (freshest info wins by recency).

### 4.4 Hook it into `BaseAgent` (one small diff)

`ai/agents/base_agent.py`, inside `record_outcome()`'s inner `_write()` function — add the call right after the existing `agent_task_outcomes` INSERT/commit, replacing the old direct `replayer.trigger_for_agent` call (which is now subsumed by `RealtimeLearner`):

```python
def _write():
    try:
        ts = __import__("datetime").datetime.now().isoformat()
        with memory_manager._lock:
            memory_manager.dbs["conversations"].execute(
                """INSERT INTO agent_task_outcomes
                   (agent_id, task_type, task_id, success, duration_ms,
                    error_summary, goal_hint, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (self.agent_id, task.task_type, task.task_id,
                 int(result.success), result.duration_ms,
                 error_summary, goal_hint, ts)
            )
            memory_manager.dbs["conversations"].commit()

        # NEW: fast-loop, per-task learning — runs for every agent on every task.
        try:
            from modules.core.realtime_learner import RealtimeLearner
            RealtimeLearner(memory_manager).process(
                agent_id=self.agent_id,
                task_type=task.task_type,
                task_id=task.task_id,
                success=result.success,
                error_summary=error_summary,
                goal_hint=goal_hint,
                duration_ms=result.duration_ms,
            )
        except Exception as e:
            import logging
            logging.getLogger("JARVIS.BaseAgent").debug(f"RealtimeLearner failed: {e}")

    except Exception as e:
        import logging
        logging.getLogger("JARVIS.BaseAgent").debug(f"Failed to record outcome: {e}")
```

The old block —

```python
if not result.success and hasattr(memory_manager, 'lifecycle') and hasattr(memory_manager.lifecycle, 'replayer'):
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(
            memory_manager.lifecycle.replayer.trigger_for_agent,
            self.agent_id, task.task_type, error_summary
        )
    except RuntimeError:
        memory_manager.lifecycle.replayer.trigger_for_agent(
            self.agent_id, task.task_type, error_summary
        )
```

— is removed. `RealtimeLearner._handle_failure` replaces it with strictly better behavior: persisted streak (survives restarts), pattern-aware reset, and it fires from inside the same background thread `_write()` already runs on, so there's no need for the `call_soon_threadsafe`/`RuntimeError` dance that existed only to hop back onto the event loop.

**This is the entire integration surface.** Because every agent (`SupervisorAgent`, `CoordinatorAgent`, `PlanningAgent`, `ExecutionAgent`, `VerificationAgent`, `RecoveryAgent`, `MemoryAgent`, `BrowserAgent`, `CodingAgent`, `DebuggingAgent`, `IntegrationAgent`, `VisionAgent`) calls `self._create_result(...)` to produce its `AgentResult`, and `_create_result` already calls `record_outcome`, all 12 agents get real-time learning for free the moment this one file changes.

### 4.5 Keep the nightly job — refactor it to reuse the shared pattern extractor

No behavior change needed in `modules/core/memory_lifecycle.py::run_nightly()` — it keeps calling `AgentSelfReflector`, `AgentCapabilityTracker`, and `ExperienceReplay.run()` exactly as today, on the same schedule. This is intentional: the nightly pass is the only place with visibility into the *full* 30-day/50-run history, decay, and cross-agent merges, and it should keep being the authority that overwrites `success_rate`/`total_runs`/`confidence` with ground truth. Only two tiny internal edits inside the existing nightly modules:

- `agent_self_reflector.py::_extract_failure_clusters` → delegate to `failure_patterns.extract_pattern` (§4.2).
- `experience_replay.py::_extract_failure_pattern` → delegate to `failure_patterns.extract_pattern` (§4.2).
- `experience_replay.py::trigger_for_agent` and its `_agent_failure_counts` dict can be **deleted** — `RealtimeLearner` fully replaces this real-time-trigger responsibility, and nothing else in the codebase calls `trigger_for_agent` once the `base_agent.py` diff in §4.4 lands (confirmed via `grep` — it's only referenced from `base_agent.py` and its own definition).

---

## 5. Why this doesn't collide with the nightly job

| Table | Written by fast loop | Written by nightly | Conflict? |
|---|---|---|---|
| `agent_task_outcomes` | Insert only (unchanged, pre-existing) | Read only | No |
| `agent_capability_scores.ema_score` | **Owns this column exclusively** | Never touches it | No |
| `agent_capability_scores.success_rate/total_runs/confidence` | Never touches these | **Owns them exclusively** | No |
| `agent_self_model` | Upserts only when EMA crosses ±threshold | Upserts only when nightly confidence crosses ±threshold | Last-writer-wins by design — whichever fired most recently is the freshest signal, which is exactly what you want in a self-model |
| `agent_failure_streaks` | Owns exclusively | Not touched | No |
| `lessons_learned` / `procedural_memories` | Inserts via shared `_store_lesson`, keyed by distinct `rt_*` source patterns | Inserts via same method, keyed by its own source patterns (`captcha_triggered`, `workflow_fail:*`, `tool_fail:*`) | Namespaced apart (`rt_` prefix) — no key collisions, both are visible side by side in `build_context()`'s "LESSONS LEARNED" section |
| `agent_reflections` | Inserts with `period='realtime'` | Inserts with `period='agent_daily'/'daily'/'weekly'/'monthly'` | `get_agent_reflections(days=3)` already reads across periods indiscriminately — both surface together, sorted by recency |

---

## 6. The Architect (Supervisor) coverage gap — and how to close it

`SupervisorAgent.handle()` today only produces a tracked `AgentResult` for the `"speak"` task type (see `ai/agents/supervisor/agent.py` lines 207–233). Everything else the architect actually does — the context-retrieval dispatch, the low-confidence → verification hand-off, and reconnect-loop handling inside `run_session()` — happens as direct `await self.bus.dispatch(...)` calls or bare `try/except` blocks that never reach `_create_result()`. That means the agent most responsible for *routing* decisions currently builds the thinnest self-model of the twelve.

Recommended follow-up (same pattern, no new machinery — just route existing Supervisor logic through the same result path everything else already uses):

```python
# Inside run_session(), after context_result / verify_result are obtained:
self._create_result(
    context_task,
    success=context_result.success,
    result={"used_verification": context_result is not verify_result and getattr(verify_result, "success", None)},
    confidence=getattr(context_result, "confidence", 0.0),
    source="supervisor_routing",
)
```

```python
# Inside the reconnect while-loop, on each disconnect:
recon_task = AgentTask(
    task_id=str(uuid.uuid4()),
    task_type="session_reconnect",
    payload={"reason": str(e)},
    origin_agent=self.agent_id,
    target_agent=self.agent_id,
)
self._create_result(recon_task, success=False, error=str(e), source="supervisor_session")
```

Once these two spots are wired through `_create_result`, the architect gets its own `session_reconnect` and `retrieve_context`/routing capability rows in `agent_capability_scores`/`agent_self_model`, and — like every other agent — starts learning from them after every occurrence via the same `RealtimeLearner` hook, with zero additional code beyond what's already proposed in §4.

---

## 7. Guardrails (noise, performance, safety)

- **Never blocks the response path.** `RealtimeLearner.process()` runs inside the exact same background thread (`asyncio.to_thread` / `threading.Thread(daemon=True)`) that `record_outcome()` already uses today — the agent's `AgentResult` is returned to its caller before this ever executes.
- **Exception-isolated.** Wrapped in its own `try/except` inside `_write()`, matching the existing pattern — a bug in the learning path can never break task execution or the outcome-logging path.
- **No noisy single-failure lessons.** `_MIN_STREAK_FOR_INSTANT_LESSON = 2` and the streak resets whenever the failure *pattern* changes, so one-off flukes don't pollute `lessons_learned`. (Tune this constant if you find 2 is still too eager for a particular agent — it's a single module-level constant.)
- **EMA is bounded and self-correcting.** Nightly `AgentCapabilityTracker.run_nightly()` still recomputes `success_rate` from the true last-50-run window every night, so even if the fast loop's EMA drifts during the day, it's re-anchored every 24h.
- **No schema breakage.** All additions are new tables or `_safe_alter`-style additive columns with defaults — safe on an existing production DB, consistent with every other migration already in `memory_manager.py`.

---

## 8. Rollout Checklist

1. Add `modules/core/failure_patterns.py` (new file, §4.2).
2. Add `modules/core/realtime_learner.py` (new file, §4.3).
3. Schema migration in `modules/core/memory_manager.py` (§4.1) — `agent_failure_streaks` table + `ema_score`/`last_task_id` columns on `agent_capability_scores`.
4. Edit `ai/agents/base_agent.py::record_outcome._write()` — call `RealtimeLearner.process(...)`, remove the old `trigger_for_agent` call (§4.4).
5. Delete `ExperienceReplay.trigger_for_agent` and `_agent_failure_counts` (dead code after step 4).
6. Point `experience_replay.py::_extract_failure_pattern` and `agent_self_reflector.py::_extract_failure_clusters` at `failure_patterns.extract_pattern` (§4.5).
7. (Follow-up, separate PR) Wire Supervisor's routing/reconnect logic through `_create_result` per §6.
8. Manual verification:
   - Trigger two consecutive same-pattern failures on any agent → confirm a `lessons_learned` row appears immediately (no restart, no waiting for 03:05) with `source_pattern` prefixed `rt_`.
   - Restart the process mid-streak → confirm the streak count in `agent_failure_streaks` survives (this is the specific bug being fixed vs. the old in-memory dict).
   - Run a handful of successful tasks for one agent/task_type → query `agent_capability_scores.ema_score` and confirm it climbs toward 1.0 without `success_rate`/`total_runs` changing until the next nightly run.
   - Confirm `tests/test_agents/test_all_agents.py` still passes unmodified — the change is additive and internal to `record_outcome`, no public agent interfaces change.

---

## 9. Summary of files touched

| File | Change |
|---|---|
| `modules/core/failure_patterns.py` | **New** — shared pattern extractor |
| `modules/core/realtime_learner.py` | **New** — the fast loop |
| `modules/core/memory_manager.py` | Schema additions (1 new table, 2 new columns) |
| `ai/agents/base_agent.py` | ~15-line change inside `record_outcome._write()` |
| `modules/core/experience_replay.py` | Delegate pattern extraction; delete `trigger_for_agent`/`_agent_failure_counts` |
| `modules/core/agent_self_reflector.py` | Delegate pattern extraction |
| `ai/agents/supervisor/agent.py` | *(follow-up)* route routing/reconnect events through `_create_result` |

No changes required to: `modules/core/memory_lifecycle.py` (nightly schedule untouched), `modules/core/agent_capability_tracker.py` (nightly ground-truth logic untouched), any of the other 10 agent files (they all inherit the fix through `BaseAgent`), or `build_context()` (already reads live from the tables the fast loop now populates sooner).