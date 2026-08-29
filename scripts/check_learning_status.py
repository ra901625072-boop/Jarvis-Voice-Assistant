"""
check_learning_status.py
-------------------------
Python-based monitoring dashboard for the JARVIS learning pipeline.
Replaces the need for sqlite3 CLI (not available on Windows by default).

HOW TO RUN
    cd d:\\Jarvis
    python check_learning_status.py

All queries run read-only against apps/backend/database/memory/memory.db.
"""

import sqlite3
import os
import sys

# Force UTF-8 output on Windows (prevents cp1252 encoding errors with ANSI/Unicode).
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ------------------------------------------------------------------ #
# Paths                                                                #
# ------------------------------------------------------------------ #

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND_DIR = os.path.join(_ROOT_DIR, "apps", "backend")
_DB_PATH = os.path.join(_BACKEND_DIR, "database", "memory", "memory.db")

# ------------------------------------------------------------------ #
# ANSI helpers                                                         #
# ------------------------------------------------------------------ #

_GREEN = "\033[92m"
_RED   = "\033[91m"
_CYAN  = "\033[96m"
_YELLOW = "\033[93m"
_DIM   = "\033[2m"
_BOLD  = "\033[1m"
_RESET = "\033[0m"

# All 12 known agent IDs for coverage gap reporting.
ALL_AGENTS = [
    "supervisor_agent", "coordinator_agent", "planning_agent",
    "execution_agent", "verification_agent", "recovery_agent",
    "memory_agent", "browser_agent", "coding_agent",
    "debugging_agent", "integration_agent", "vision_agent",
]


def _head(num, title):
    return f"\n{_BOLD}{_CYAN}{'─' * 60}\n  Q{num}. {title}\n{'─' * 60}{_RESET}"


def _table(headers, rows, col_widths=None):
    """Print a simple formatted table."""
    if not rows:
        print(f"  {_DIM}(no data){_RESET}")
        return
    if col_widths is None:
        col_widths = []
        for i, h in enumerate(headers):
            w = len(h)
            for r in rows:
                val = str(r[i]) if i < len(r) else ""
                w = max(w, min(len(val), 50))
            col_widths.append(w + 2)

    # Header
    hdr = "  "
    sep = "  "
    for i, h in enumerate(headers):
        hdr += f"{h:<{col_widths[i]}}"
        sep += f"{'─' * col_widths[i]}"
    print(hdr)
    print(sep)

    # Rows
    for r in rows:
        line = "  "
        for i, val in enumerate(r):
            s = str(val) if val is not None else "—"
            if len(s) > 48:
                s = s[:48] + "…"
            line += f"{s:<{col_widths[i]}}"
        print(line)


def main():
    if not os.path.exists(_DB_PATH):
        print(f"{_RED}Database not found at: {_DB_PATH}{_RESET}")
        print(f"Make sure you're running from the Jarvis project root.")
        sys.exit(1)

    conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # ── Q1: Coverage ──
    print(_head(1, "Coverage: which agents have outcome data?"))
    rows = conn.execute("""
        SELECT agent_id, task_type, COUNT(*) AS runs,
               SUM(success) AS successes,
               COUNT(*) - SUM(success) AS failures,
               MIN(created_at) AS first_seen,
               MAX(created_at) AS last_seen
        FROM agent_task_outcomes
        WHERE goal_hint NOT LIKE 'seed_%' OR goal_hint IS NULL
        GROUP BY agent_id, task_type
        ORDER BY runs DESC
    """).fetchall()
    _table(["agent_id", "task_type", "runs", "ok", "fail", "first_seen", "last_seen"],
           [tuple(r) for r in rows])

    # ── Q2: Live confidence ──
    print(_head(2, "Live confidence (EMA) vs ground-truth (nightly)"))
    rows = conn.execute("""
        SELECT agent_id, task_type, ema_score, success_rate, total_runs, confidence, last_updated
        FROM agent_capability_scores
        ORDER BY ema_score ASC
    """).fetchall()
    _table(["agent_id", "task_type", "ema", "rate", "runs", "conf", "updated"],
           [tuple(r) for r in rows])

    # ── Q3: Active failure streaks ──
    print(_head(3, "Active failure streaks (persisted, survives restarts)"))
    rows = conn.execute("""
        SELECT agent_id, task_type, streak, last_pattern, updated_at
        FROM agent_failure_streaks
        WHERE streak > 0
        ORDER BY streak DESC
    """).fetchall()
    _table(["agent_id", "task_type", "streak", "pattern", "updated"],
           [tuple(r) for r in rows])

    # ── Q4: Lessons learned ──
    print(_head(4, "Lessons learned (most recent 20)"))
    rows = conn.execute("""
        SELECT lesson, source_pattern, occurrence_count, created_at
        FROM lessons_learned
        ORDER BY created_at DESC
        LIMIT 20
    """).fetchall()
    _table(["lesson", "source", "count", "created"],
           [tuple(r) for r in rows])

    # ── Q5: Self-model ──
    print(_head(5, "Self-model: what the system believes about itself"))
    rows = conn.execute("""
        SELECT capability, category, confidence, notes, created_at
        FROM agent_self_model
        ORDER BY confidence ASC
    """).fetchall()
    _table(["capability", "category", "conf", "notes", "created"],
           [tuple(r) for r in rows])

    # ── Q6: Freshest reflections ──
    print(_head(6, "Freshest reflections (last 15)"))
    rows = conn.execute("""
        SELECT reflection, period, created_at
        FROM agent_reflections
        ORDER BY created_at DESC
        LIMIT 15
    """).fetchall()
    _table(["reflection", "period", "created"],
           [tuple(r) for r in rows])

    # ── Q7: Nightly job freshness ──
    print(_head(7, "Has the nightly job (03:05) run recently?"))
    rows = conn.execute("""
        SELECT period, COUNT(*) as total, MAX(created_at) AS most_recent
        FROM agent_reflections
        WHERE period != 'realtime'
        GROUP BY period
    """).fetchall()
    _table(["period", "total", "most_recent"],
           [tuple(r) for r in rows])

    # ── Q8: Coverage gap ──
    print(_head(8, "Coverage gap: which of the 12 agents have ZERO outcomes?"))
    agents_with_data = set()
    for r in conn.execute("SELECT DISTINCT agent_id FROM agent_task_outcomes WHERE goal_hint NOT LIKE 'seed_%' OR goal_hint IS NULL"):
        agents_with_data.add(r[0])
    missing = [a for a in ALL_AGENTS if a not in agents_with_data]
    if missing:
        for a in missing:
            print(f"  {_RED}✗{_RESET} {a}")
        print(f"\n  {_YELLOW}{len(missing)} of {len(ALL_AGENTS)} agents have never produced an outcome.{_RESET}")
    else:
        print(f"  {_GREEN}All {len(ALL_AGENTS)} agents have outcome data!{_RESET}")

    # ── Q9: EMA vs ground-truth drift ──
    print(_head(9, "EMA vs ground-truth drift (|ema - success_rate| > 0.15)"))
    rows = conn.execute("""
        SELECT agent_id, task_type, ema_score, success_rate, total_runs,
               ROUND(ABS(ema_score - success_rate), 4) AS drift
        FROM agent_capability_scores
        WHERE ABS(ema_score - success_rate) > 0.15 AND total_runs >= 3
        ORDER BY drift DESC
    """).fetchall()
    if rows:
        _table(["agent_id", "task_type", "ema", "rate", "runs", "drift"],
               [tuple(r) for r in rows])
        print(f"\n  {_YELLOW}These agents have significant EMA/ground-truth disagreement.{_RESET}")
    else:
        print(f"  {_GREEN}No significant drift detected (or insufficient data).{_RESET}")

    # ── Summary ──
    total_outcomes = conn.execute("SELECT COUNT(*) FROM agent_task_outcomes WHERE goal_hint NOT LIKE 'seed_%' OR goal_hint IS NULL").fetchone()[0]
    total_failures = conn.execute("SELECT COUNT(*) FROM agent_task_outcomes WHERE success = 0 AND (goal_hint NOT LIKE 'seed_%' OR goal_hint IS NULL)").fetchone()[0]
    total_lessons = conn.execute("SELECT COUNT(*) FROM lessons_learned").fetchone()[0]
    agents_covered = len(agents_with_data)

    print(f"\n{_BOLD}{'═' * 60}")
    print(f"  SUMMARY")
    print(f"{'═' * 60}{_RESET}")
    print(f"  Total outcomes:     {total_outcomes}")
    print(f"  Total failures:     {total_failures}")
    print(f"  Lessons learned:    {total_lessons}")
    print(f"  Agent coverage:     {agents_covered}/{len(ALL_AGENTS)}")
    coverage_color = _GREEN if agents_covered == len(ALL_AGENTS) else (_YELLOW if agents_covered >= 6 else _RED)
    print(f"  Health:             {coverage_color}{'FULL' if agents_covered == len(ALL_AGENTS) else f'{len(ALL_AGENTS) - agents_covered} agents need exercise'}{_RESET}")
    print()

    conn.close()


if __name__ == "__main__":
    main()
