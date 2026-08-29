"""
train_loop.py
-------------
Automated training loop for JARVIS's two-speed learning system.
Runs simulated agent workloads and triggers memory consolidations repeatedly,
surfacing learning dashboard metrics dynamically.

Usage:
    python train_loop.py --iterations 3 --delay 2
    python train_loop.py --clean
"""

import os
import sys
import time
import sqlite3
import subprocess
import argparse
import logging

# Force UTF-8 output on Windows for clean ANSI display
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Resolve paths
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.join(_ROOT_DIR, "apps", "backend")
_DEFAULT_DB_PATH = os.path.join(_BACKEND_DIR, "database", "memory", "memory.db")

# Setup Logging
logger = logging.getLogger("train_loop")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")

# File handler
file_handler = logging.FileHandler(os.path.join(_ROOT_DIR, "train_loop.log"), encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Console handler
class ConsoleHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

console_handler = ConsoleHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(console_handler)

# ANSI Colors
_GREEN = "\033[92m"
_RED   = "\033[91m"
_CYAN  = "\033[96m"
_YELLOW = "\033[93m"
_DIM   = "\033[2m"
_BOLD  = "\033[1m"
_RESET = "\033[0m"


def print_title(title):
    logger.info(f"\n{_BOLD}{_CYAN}╔═{'═' * len(title)}═╗")
    logger.info(f"║ {title} ║")
    logger.info(f"╚═{'═' * len(title)}═╝{_RESET}")


def print_step(step_name):
    logger.info(f"\n{_BOLD}{_YELLOW}➤ {step_name}...{_RESET}")


def get_db_connection(db_path):
    if not os.path.exists(db_path):
        return None
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def get_summary_stats(db_path):
    conn = get_db_connection(db_path)
    if not conn:
        return None
    
    conn.row_factory = sqlite3.Row
    try:
        total_outcomes = conn.execute(
            "SELECT COUNT(*) FROM agent_task_outcomes WHERE goal_hint NOT LIKE 'seed_%' AND goal_hint NOT LIKE 'e2e_sim_%'"
        ).fetchone()[0]
        
        total_failures = conn.execute(
            "SELECT COUNT(*) FROM agent_task_outcomes WHERE success = 0 AND goal_hint NOT LIKE 'seed_%' AND goal_hint NOT LIKE 'e2e_sim_%'"
        ).fetchone()[0]

        total_sim_outcomes = conn.execute(
            "SELECT COUNT(*) FROM agent_task_outcomes WHERE goal_hint LIKE 'e2e_sim_%'"
        ).fetchone()[0]
        
        total_sim_failures = conn.execute(
            "SELECT COUNT(*) FROM agent_task_outcomes WHERE success = 0 AND goal_hint LIKE 'e2e_sim_%'"
        ).fetchone()[0]

        total_seeded_outcomes = conn.execute(
            "SELECT COUNT(*) FROM agent_task_outcomes WHERE goal_hint LIKE 'seed_%'"
        ).fetchone()[0]
        
        total_seeded_failures = conn.execute(
            "SELECT COUNT(*) FROM agent_task_outcomes WHERE success = 0 AND goal_hint LIKE 'seed_%'"
        ).fetchone()[0]
        
        total_lessons = conn.execute("SELECT COUNT(*) FROM lessons_learned").fetchone()[0]
        
        rt_lessons = conn.execute(
            "SELECT COUNT(*) FROM lessons_learned WHERE source_pattern LIKE 'rt_%'"
        ).fetchone()[0]

        seed_rt_lessons = conn.execute(
            "SELECT COUNT(*) FROM lessons_learned WHERE source_pattern LIKE 'seed_rt_%'"
        ).fetchone()[0]
        
        active_streaks = conn.execute(
            "SELECT COUNT(*) FROM agent_failure_streaks WHERE streak > 0"
        ).fetchone()[0]
        
        self_models = conn.execute("SELECT COUNT(*) FROM agent_self_model").fetchone()[0]
        
        reflections = conn.execute("SELECT COUNT(*) FROM agent_reflections").fetchone()[0]

        high_conf_ema = conn.execute(
            "SELECT COUNT(*) FROM agent_capability_scores WHERE ema_score >= 0.8"
        ).fetchone()[0]
        
        total_scores = conn.execute("SELECT COUNT(*) FROM agent_capability_scores").fetchone()[0]

        success_patterns_count = conn.execute("SELECT COUNT(*) FROM success_patterns").fetchone()[0]

        return {
            "total_outcomes": total_outcomes,
            "total_failures": total_failures,
            "total_sim_outcomes": total_sim_outcomes,
            "total_sim_failures": total_sim_failures,
            "total_seeded_outcomes": total_seeded_outcomes,
            "total_seeded_failures": total_seeded_failures,
            "lessons": total_lessons,
            "rt_lessons": rt_lessons,
            "seed_rt_lessons": seed_rt_lessons,
            "streaks": active_streaks,
            "self_models": self_models,
            "reflections": reflections,
            "high_conf_ema": high_conf_ema,
            "total_scores": total_scores,
            "success_patterns": success_patterns_count,
        }
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return None
    finally:
        conn.close()


def print_dashboard(before_stats, after_stats):
    logger.info(f"\n{_BOLD}{_CYAN}📊 Learning Pipeline Dashboard (Before ➜ After){_RESET}")
    logger.info(f"  {'Metric':32s}  {'Before':>6s} ➜ {'After':>6s}   {'Change':>8s}")
    logger.info(f"  {'─' * 32}  {'─' * 6} ─ {'─' * 6}   {'─' * 8}")

    def print_metric_row(label, key):
        b = before_stats.get(key, 0) if before_stats else 0
        a = after_stats.get(key, 0) if after_stats else 0
        diff = a - b
        if diff > 0:
            diff_str = _GREEN + f"+{diff:<6}" + _RESET
        elif diff < 0:
            diff_str = _RED + f"{diff:<6}" + _RESET
        else:
            diff_str = f"{diff:<6}"
        logger.info(f"  {label:32s}  {b:6d} ➜ {a:6d}   ({diff_str})")

    print_metric_row("Real Agent Outcomes (runs)", "total_outcomes")
    print_metric_row("Real Agent Failures (fail)", "total_failures")
    print_metric_row("Simulated Outcomes (E2E sim)", "total_sim_outcomes")
    print_metric_row("Simulated Failures (E2E sim)", "total_sim_failures")
    print_metric_row("Seeded Outcomes (smoke test)", "total_seeded_outcomes")
    print_metric_row("Seeded Failures (smoke test)", "total_seeded_failures")
    print_metric_row("Active Failure Streaks", "streaks")
    print_metric_row("Total Lessons Learned", "lessons")
    print_metric_row("  ↳ Real-world Lessons (rt_)", "rt_lessons")
    print_metric_row("  ↳ Synthetic Lessons (seed_rt_)", "seed_rt_lessons")
    print_metric_row("Agent Self-Model Nodes", "self_models")
    print_metric_row("Memory Reflections", "reflections")
    print_metric_row("High Confidence Capabilities (EMA >= 0.8)", "high_conf_ema")
    print_metric_row("Total Evaluated Capabilities", "total_scores")
    print_metric_row("Success Planner Patterns", "success_patterns")


def run_command(command_list):
    logger.info(f"  [Running] python {' '.join(command_list)}")
    res = subprocess.run(
        [sys.executable] + command_list,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=_ROOT_DIR
    )
    if res.returncode != 0:
        logger.error(f"  {_RED}❌ Error running command: {' '.join(command_list)}{_RESET}")
        logger.error(res.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Repeated training and consolidation loop for Jarvis.")
    parser.add_argument("--iterations", type=int, default=3, help="Number of training iterations (cycles) to run.")
    parser.add_argument("--delay", type=int, default=2, help="Delay in seconds between cycles.")
    parser.add_argument("--clean", action="store_true", help="Clean up seeded test data and exit.")
    parser.add_argument("--clean-first", action="store_true", help="Clean up seeded test data before starting the loop.")
    parser.add_argument("--skip-e2e", action="store_true", help="Skip the E2E mock execution phase.")
    parser.add_argument("--no-mock", action="store_true", help="Run E2E agent workflows un-mocked against real APIs.")
    parser.add_argument("--db-path", type=str, default=_DEFAULT_DB_PATH, help="Path to SQLite memory.db")
    args = parser.parse_args()

    if args.clean:
        print_step("Cleaning all simulated/seeded training data")
        if run_command(["seed_and_verify_learning.py", "--clean"]):
            logger.info(f"  {_GREEN}✓ Cleaned successfully.{_RESET}")
        else:
            logger.error(f"  {_RED}✗ Cleaning failed.{_RESET}")
            sys.exit(1)
        sys.exit(0)

    if args.clean_first:
        print_step("Pre-cleaning seeded training data")
        if not run_command(["seed_and_verify_learning.py", "--clean"]):
            logger.error(f"  {_RED}✗ Pre-cleaning failed. Aborting training loop.{_RESET}")
            sys.exit(1)

    initial_stats = get_summary_stats(args.db_path)
    if not initial_stats:
        logger.error(f"{_RED}Database not found or empty. Please run a smoke test first.{_RESET}")
        sys.exit(1)

    print_title("Starting Jarvis Training Loop")
    logger.info(f"  Target Cycles: {_BOLD}{args.iterations}{_RESET}")
    logger.info(f"  Delay:         {_BOLD}{args.delay} seconds{_RESET}")
    mode_str = "Seeding & Consolidation only" if args.skip_e2e else ("Real-World Data (un-mocked)" if args.no_mock else "E2E Simulation (mocked) + Seeding + Consolidation")
    logger.info(f"  Mode:          {mode_str}")
    logger.info(f"  Log File:      {os.path.join(_ROOT_DIR, 'train_loop.log')}")

    for i in range(1, args.iterations + 1):
        print_title(f"Cycle {i} of {args.iterations}")
        cycle_before_stats = get_summary_stats(args.db_path)

        if not args.skip_e2e:
            print_step("Step 1: Running E2E agent workflow simulations")
            cmd = ["e2e_smoke.py"]
            if args.no_mock:
                cmd.append("--no-mock")
            
            t0 = time.time()
            success = run_command(cmd)
            elapsed = time.time() - t0
            
            if success:
                logger.info(f"  {_GREEN}✓ E2E simulation executed successfully in {elapsed:.2f}s.{_RESET}")
            else:
                logger.error(f"  {_RED}✗ E2E simulation failed. Aborting training loop.{_RESET}")
                sys.exit(1)

        print_step("Step 2: Seeding capability successes and failure streaks")
        t0 = time.time()
        success = run_command(["seed_and_verify_learning.py"])
        elapsed = time.time() - t0
        if success:
            logger.info(f"  {_GREEN}✓ Seeding completed successfully in {elapsed:.2f}s.{_RESET}")
        else:
            logger.error(f"  {_RED}✗ Seeding failed. Aborting training loop.{_RESET}")
            sys.exit(1)

        print_step("Step 3: Triggering nightly memory consolidation (Slow Loop)")
        t0 = time.time()
        success = run_command(["trigger_nightly.py"])
        elapsed = time.time() - t0
        if success:
            logger.info(f"  {_GREEN}✓ Consolidation complete in {elapsed:.2f}s.{_RESET}")
        else:
            logger.error(f"  {_RED}✗ Consolidation failed. Aborting training loop.{_RESET}")
            sys.exit(1)

        cycle_after_stats = get_summary_stats(args.db_path)
        print_dashboard(cycle_before_stats, cycle_after_stats)

        if i < args.iterations:
            logger.info(f"\n{_DIM}Sleeping for {args.delay}s before next cycle...{_RESET}")
            time.sleep(args.delay)

    final_stats = get_summary_stats(args.db_path)
    print_title("Training Complete")
    print_dashboard(initial_stats, final_stats)
    logger.info(f"\n{_GREEN}{_BOLD}Success: Jarvis has been trained repeatedly!{_RESET}")
    logger.info(f"To monitor complete stats, run: {_BOLD}python check_learning_status.py{_RESET}")


if __name__ == "__main__":
    main()
