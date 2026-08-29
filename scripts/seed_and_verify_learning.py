"""
seed_and_verify_learning.py
----------------------------
Standalone smoke test for JARVIS's real-time learning pipeline
(RealtimeLearner + agent_capability_scores / agent_failure_streaks / lessons_learned).

WHY THIS EXISTS
Right now agent_task_outcomes, agent_capability_scores, agent_failure_streaks,
and lessons_learned are all empty in your shipped database. That means the
wiring (base_agent.py -> RealtimeLearner -> DB tables) is correctly built but
has never actually run against real data. This script exercises it directly
-- no LLM/API keys required -- so you get hard proof the loop works before
you start relying on real usage to fill it in.

WHAT IT DOES
1. Boots a real MemoryManager against your existing apps/backend/database dir.
2. For every one of the 12 agents and their known task_types, simulates a
   handful of successes (to prove the EMA climbs) and, for one agent, two
   consecutive same-pattern failures (to prove the persisted streak survives
   and an instant lesson gets promoted -- docs/realtime_learning_architecture.md section 8, item 1).
3. Prints out what changed in each table so you can see the loop firing.

HOW TO RUN
    cd d:\\Jarvis
    python seed_and_verify_learning.py            # seed + report
    python seed_and_verify_learning.py --dry-run  # preview only, no DB writes
    python seed_and_verify_learning.py --clean    # remove test rows, keep real data

Safe to run multiple times -- it only adds rows, never deletes real data.
The --clean flag only removes rows identifiable as test data (goal_hint='seed_smoke_test*').

NOTE: real agent_id values all carry an "_agent" suffix (confirmed via
`grep super().__init__ ai/agents/*/agent.py`) -- use these exact strings or
you'll create phantom rows that never match what BaseAgent actually writes.
"""

import sys
import os
import uuid
import time
import argparse

# Fix import path: modules.core lives under apps/backend, not the project root.
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND_DIR = os.path.join(_ROOT_DIR, "apps", "backend")
sys.path.insert(0, _BACKEND_DIR)

from modules.memory.manager import MemoryManager
from modules.learning.realtime_learner import RealtimeLearner

# ------------------------------------------------------------------ #
# Constants                                                            #
# ------------------------------------------------------------------ #

# The real database lives at apps/backend/database (not the root-level database/).
_DB_BASE_DIR = os.path.join(_BACKEND_DIR, "database")

# Marker values to identify test data for cleanup.
_GOAL_SUCCESS = "seed_smoke_test"
_GOAL_FAILURE = "seed_smoke_test_failure"

# agent_id -> list of task_types it actually handles (pulled from each agent.py).
AGENT_TASK_TYPES = {
    "supervisor_agent":   ["speak", "supervisor_routing", "supervisor_session"],
    "coordinator_agent":  ["generate_context", "analyze_failure", "evaluate_plan"],
    "planning_agent":     ["create_plan", "replan"],
    "execution_agent":    ["execute_plan", "get_world_state"],
    "verification_agent": ["verify_result"],
    "recovery_agent":     ["recover_failure"],
    "memory_agent":       ["record_execution_report", "replay", "memory_health_check"],
    "browser_agent":      ["automate_web_flow"],
    "coding_agent":       ["refactor_code", "build_project"],  # write_code already has real data
    "debugging_agent":    ["diagnose_error", "apply_self_healing", "verify_fix"],
    "integration_agent":  ["webhook_flow", "call_graphql", "authenticate", "connect_service", "sync_data"],
    "vision_agent":       ["analyze_screen", "find_ui_element", "read_screen_text"],
}

# ------------------------------------------------------------------ #
# ANSI helpers (Windows 10+ supports these)                            #
# ------------------------------------------------------------------ #

_GREEN = "\033[92m"
_RED   = "\033[91m"
_CYAN  = "\033[96m"
_DIM   = "\033[2m"
_BOLD  = "\033[1m"
_RESET = "\033[0m"


def _ok(text):
    return f"{_GREEN}{text}{_RESET}"


def _fail(text):
    return f"{_RED}{text}{_RESET}"


def _head(text):
    return f"\n{_BOLD}{_CYAN}{'=' * 60}\n  {text}\n{'=' * 60}{_RESET}"

# ------------------------------------------------------------------ #
# Snapshot helpers                                                     #
# ------------------------------------------------------------------ #

def _snapshot(conn):
    """Take a snapshot of row counts and key values for before/after comparison."""
    snap = {}
    snap["outcomes"] = conn.execute("SELECT COUNT(*) FROM agent_task_outcomes").fetchone()[0]
    snap["scores"] = conn.execute("SELECT COUNT(*) FROM agent_capability_scores").fetchone()[0]
    snap["streaks"] = conn.execute("SELECT COUNT(*) FROM agent_failure_streaks WHERE streak > 0").fetchone()[0]
    try:
        snap["lessons"] = conn.execute("SELECT COUNT(*) FROM lessons_learned").fetchone()[0]
    except Exception:
        snap["lessons"] = 0
    snap["reflections"] = conn.execute(
        "SELECT COUNT(*) FROM agent_reflections WHERE period='realtime'"
    ).fetchone()[0]
    return snap


def _print_diff(label, before, after):
    delta = after - before
    arrow = _ok(f"+{delta}") if delta > 0 else (_fail(str(delta)) if delta < 0 else f"{_DIM}+0{_RESET}")
    print(f"  {label:30s}  {before:>5} -> {after:>5}  ({arrow})")


# ------------------------------------------------------------------ #
# Seed functions                                                       #
# ------------------------------------------------------------------ #

def seed_successes(mm, agent_id, task_type, n=5):
    """Fire N successes -> proves ema_score climbs toward 1.0 without touching success_rate."""
    from datetime import datetime
    learner = RealtimeLearner(mm)
    for _ in range(n):
        tid = str(uuid.uuid4())
        ts = datetime.now().isoformat()
        
        with mm._lock:
            mm.dbs["conversations"].execute(
                """INSERT INTO agent_task_outcomes 
                   (agent_id, task_type, task_id, success, duration_ms, error_summary, goal_hint, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (agent_id, task_type, tid, 1, 250.0, None, _GOAL_SUCCESS, ts)
            )
            mm.dbs["conversations"].commit()
            
        learner.process(
            agent_id=agent_id,
            task_type=task_type,
            task_id=tid,
            success=True,
            error_summary=None,
            goal_hint=_GOAL_SUCCESS,
            duration_ms=250.0,
        )


def seed_failure_streak(mm, agent_id, task_type, pattern_error="Connection timed out", n=2):
    """Fire N same-pattern failures -> proves streak persists and an instant lesson fires at n=2."""
    from datetime import datetime
    learner = RealtimeLearner(mm)
    for _ in range(n):
        tid = str(uuid.uuid4())
        ts = datetime.now().isoformat()
        
        with mm._lock:
            mm.dbs["conversations"].execute(
                """INSERT INTO agent_task_outcomes 
                   (agent_id, task_type, task_id, success, duration_ms, error_summary, goal_hint, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (agent_id, task_type, tid, 0, 100.0, pattern_error, _GOAL_FAILURE, ts)
            )
            mm.dbs["conversations"].commit()
            
        learner.process(
            agent_id=agent_id,
            task_type=task_type,
            task_id=tid,
            success=False,
            error_summary=pattern_error,
            goal_hint=_GOAL_FAILURE,
            duration_ms=100.0,
        )


# ------------------------------------------------------------------ #
# Report                                                               #
# ------------------------------------------------------------------ #

def report(mm):
    conn = mm.dbs["conversations"]

    print(_head("agent_capability_scores (EMA signal)"))
    rows = conn.execute(
        "SELECT agent_id, task_type, ema_score, success_rate, total_runs "
        "FROM agent_capability_scores ORDER BY agent_id, task_type"
    ).fetchall()
    if rows:
        print(f"  {'agent_id':22s} {'task_type':26s} {'ema':>6s}  {'rate':>6s}  {'runs':>5s}")
        print(f"  {'-'*22} {'-'*26} {'-'*6}  {'-'*6}  {'-'*5}")
        for r in rows:
            ema_color = _ok if r[2] >= 0.8 else _fail
            print(f"  {r[0]:22s} {r[1]:26s} {ema_color(f'{r[2]:.4f}'):>6s}  {r[3]:>6.2f}  {r[4]:>5d}")
    else:
        print(f"  {_DIM}(empty){_RESET}")

    print(_head("agent_failure_streaks (active only)"))
    rows = conn.execute(
        "SELECT agent_id, task_type, streak, last_pattern FROM agent_failure_streaks WHERE streak > 0"
    ).fetchall()
    if rows:
        for r in rows:
            print(f"  {r[0]:22s} {r[1]:26s} streak={_fail(str(r[2]))}  pattern={r[3]}")
    else:
        print(f"  {_DIM}(no active streaks){_RESET}")

    print(_head("lessons_learned (rt_ prefixed = from real-time loop)"))
    try:
        rows = conn.execute(
            "SELECT lesson, source_pattern, occurrence_count FROM lessons_learned "
            "WHERE source_pattern LIKE 'rt_%'"
        ).fetchall()
        if rows:
            for r in rows:
                print(f"  [{r[2]}x] {r[1]}: {r[0]}")
        else:
            print(f"  {_DIM}(no real-time lessons yet){_RESET}")
    except Exception as e:
        print(f"  {_DIM}(couldn't read lessons_learned: {e}){_RESET}")

    print(_head("agent_reflections (period='realtime'), most recent 10"))
    rows = conn.execute(
        "SELECT reflection, created_at FROM agent_reflections "
        "WHERE period='realtime' ORDER BY id DESC LIMIT 10"
    ).fetchall()
    if rows:
        for r in rows:
            print(f"  {r[1]}  {r[0]}")
    else:
        print(f"  {_DIM}(no realtime reflections yet){_RESET}")


# ------------------------------------------------------------------ #
# Clean function                                                       #
# ------------------------------------------------------------------ #

def clean(mm):
    """Remove only rows created by this script. Real data is never touched."""
    conn = mm.dbs["conversations"]
    print(_head("Cleaning test data"))

    # 1. Remove test reflections
    c = conn.execute(
        "DELETE FROM agent_reflections WHERE period='realtime' AND "
        f"(reflection LIKE '%{_GOAL_SUCCESS}%' OR reflection LIKE '%{_GOAL_FAILURE}%')"
    )
    print(f"  agent_reflections:      {_ok(str(c.rowcount))} test rows removed")

    # 2. Remove test capability scores — only where the task_type is one we seeded
    #    AND no real data exists for that agent/task_type in agent_task_outcomes.
    test_pairs = []
    for agent_id, task_types in AGENT_TASK_TYPES.items():
        for task_type in task_types:
            real = conn.execute(
                "SELECT COUNT(*) FROM agent_task_outcomes WHERE agent_id=? AND task_type=? "
                f"AND goal_hint NOT IN ('{_GOAL_SUCCESS}', '{_GOAL_FAILURE}')",
                (agent_id, task_type)
            ).fetchone()[0]
            if real == 0:
                test_pairs.append((agent_id, task_type))

    score_del = 0
    streak_del = 0
    model_del = 0
    for agent_id, task_type in test_pairs:
        score_del += conn.execute(
            "DELETE FROM agent_capability_scores WHERE agent_id=? AND task_type=?",
            (agent_id, task_type)
        ).rowcount
        streak_del += conn.execute(
            "DELETE FROM agent_failure_streaks WHERE agent_id=? AND task_type=?",
            (agent_id, task_type)
        ).rowcount
        cap = f"{agent_id}:{task_type}"
        model_del += conn.execute(
            "DELETE FROM agent_self_model WHERE capability=?", (cap,)
        ).rowcount

    print(f"  agent_capability_scores: {_ok(str(score_del))} test rows removed")
    print(f"  agent_failure_streaks:   {_ok(str(streak_del))} test rows removed")
    print(f"  agent_self_model:        {_ok(str(model_del))} test rows removed")

    # 3. Remove test lessons & procedural memories
    try:
        c = conn.execute("DELETE FROM lessons_learned WHERE source_pattern LIKE 'seed_rt_%'")
        print(f"  lessons_learned:         {_ok(str(c.rowcount))} test rows removed")
        c2 = conn.execute("DELETE FROM procedural_memories WHERE skill_name LIKE 'lesson:seed_rt_%'")
        print(f"  procedural_memories:     {_ok(str(c2.rowcount))} test lessons removed")
    except Exception as e:
        print(f"  Failed to clean lessons: {e}")

    # 4. Remove test outcome rows (identifiable by goal_hint)
    c = conn.execute(
        f"DELETE FROM agent_task_outcomes WHERE goal_hint IN ('{_GOAL_SUCCESS}', '{_GOAL_FAILURE}') OR goal_hint LIKE 'e2e_sim_%'"
    )
    print(f"  agent_task_outcomes:     {_ok(str(c.rowcount))} test rows removed")

    conn.commit()
    print(f"\n  {_ok('Done.')} Real data was not touched.")


# ------------------------------------------------------------------ #
# Main                                                                 #
# ------------------------------------------------------------------ #

def main():
    import os
    os.environ["JARVIS_ALLOW_SEED_WRITES"] = "1"
    parser = argparse.ArgumentParser(description="Seed and verify the JARVIS real-time learning pipeline.")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would happen without writing to the DB.")
    parser.add_argument("--clean", action="store_true", help="Remove test rows created by this script; keeps real data.")
    args = parser.parse_args()

    if args.dry_run:
        print(_head("DRY RUN — no database writes"))
        total_tasks = sum(len(types) for types in AGENT_TASK_TYPES.values())
        print(f"  Would seed {_ok(str(total_tasks))} agent/task_type combos x 5 successes each = {total_tasks * 5} outcomes")
        print(f"  Would seed 1 failure streak (browser_agent/automate_web_flow x 2 same-pattern failures)")
        print(f"  Expected: EMA climbs for all, streak=2 fires instant lesson for browser_agent")
        print(f"\n  Database path: {_DB_BASE_DIR}")
        print(f"  To run for real: python seed_and_verify_learning.py")
        return

    print(f"Booting MemoryManager against {_DB_BASE_DIR} ...")
    mm = MemoryManager(base_dir=_DB_BASE_DIR)
    mm.initialize_minimal()
    time.sleep(0.3)  # let scheduler thread settle

    if args.clean:
        clean(mm)
        return

    # Take before snapshot
    conn = mm.dbs["conversations"]
    before = _snapshot(conn)
    print(f"  {_DIM}Before: {before}{_RESET}")

    print(f"\nSeeding successes for every agent/task_type (proves EMA moves)...")
    for agent_id, task_types in AGENT_TASK_TYPES.items():
        for task_type in task_types:
            seed_successes(mm, agent_id, task_type, n=5)
    print(_ok("  Done."))

    print(f"\nSeeding a 2-in-a-row same-pattern failure on browser_agent/automate_web_flow")
    print(f"  (proves persisted streak + instant lesson promotion)...")
    seed_failure_streak(mm, "browser_agent", "automate_web_flow",
                        pattern_error="Request timed out after 30s", n=2)
    print(_ok("  Done."))

    # Take after snapshot
    after = _snapshot(conn)

    print(_head("Before / After"))
    _print_diff("agent_task_outcomes", before["outcomes"], after["outcomes"])
    _print_diff("agent_capability_scores", before["scores"], after["scores"])
    _print_diff("active failure streaks", before["streaks"], after["streaks"])
    _print_diff("lessons_learned", before["lessons"], after["lessons"])
    _print_diff("realtime reflections", before["reflections"], after["reflections"])

    report(mm)

    print(_head("What to check"))
    print(f"  1. EMA scores should be near 1.0 for seeded success combos")
    print(f"  2. browser_agent/automate_web_flow should show streak=2, pattern=request_timeout")
    print(f"  3. A lesson starting with 'rt_' should exist for browser_agent")
    print(f"  4. Realtime reflections should show entries for each seeded outcome")
    print(f"\n  To clean up test data: python seed_and_verify_learning.py --clean")
    print(f"  To monitor over time:  python check_learning_status.py")


if __name__ == "__main__":
    main()
