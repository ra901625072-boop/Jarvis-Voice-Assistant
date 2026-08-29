"""
trigger_nightly.py
-------------------
Manually trigger the nightly maintenance job (normally scheduled for 03:05).
Useful for testing the slow-loop ground-truth recomputation without waiting
for the scheduler, or after seeding new data via seed_and_verify_learning.py.

HOW TO RUN
    cd d:\\Jarvis
    python trigger_nightly.py

This will:
  1. Boot MemoryManager against apps/backend/database
  2. Call run_nightly_maintenance() — which runs AgentSelfReflector,
     AgentCapabilityTracker, ExperienceReplay, decay/merge/prune
  3. Force a WAL checkpoint
  4. Exit

Safe to run at any time. The nightly job is idempotent.
"""

import sys
import os
import time

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND_DIR = os.path.join(_ROOT_DIR, "apps", "backend")
sys.path.insert(0, _BACKEND_DIR)

_DB_BASE_DIR = os.path.join(_BACKEND_DIR, "database")


def main():
    print(f"Booting MemoryManager against {_DB_BASE_DIR} ...")
    from modules.memory.manager import MemoryManager
    mm = MemoryManager(base_dir=_DB_BASE_DIR)
    time.sleep(0.3)

    print("Running nightly maintenance (AgentSelfReflector + AgentCapabilityTracker + ExperienceReplay)...")
    t0 = time.time()
    mm.run_nightly_maintenance()
    elapsed = time.time() - t0
    print(f"Done in {elapsed:.1f}s.")

    print("\nRun check_learning_status.py to see the updated state.")


if __name__ == "__main__":
    main()
