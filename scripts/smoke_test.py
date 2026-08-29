import asyncio
import sys
import os
import time
import uuid

# Adjust path to find modules inside apps/backend
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "backend"))
sys.path.insert(0, backend_dir)

from config.settings import load_config
load_config()

from container import build_container
from ai.agents.types import AgentTask, AgentResult

async def main():
    print("--------------------------------------------------")
    print("JARVIS Phase 2 Bootable Smoke Test Harness")
    print("--------------------------------------------------")

    print("\n[1] Building Service Container...")
    try:
        container = build_container()
        print("-> Container built successfully.")
        
        # Eagerly initialize tools list and cache it on the container
        from modules.skills.registry import SkillRegistry
        from tools.builtin import (
            SystemTools, WindowTools, AppTools, BrowserTools, MediaTools,
            KeyboardTools, MouseTools, FileTools, TaskTools, MemoryTools,
            VerificationTools, VisionTools
        )
        from modules.planning.task_planner import TaskPlannerTools

        skill_registry = SkillRegistry(
            memory=container.get("memory"),
            security=container.get("security"),
            room=None,
            verification=container.get("verification"),
        )
        skills_list = skill_registry.load_skills()

        tools_base = [
            SystemTools(security=container.get("security")),
            WindowTools(security=container.get("security")),
            AppTools(security=container.get("security")),
            BrowserTools(security=container.get("security")),
            MediaTools(security=container.get("security")),
            KeyboardTools(security=container.get("security")),
            MouseTools(security=container.get("security")),
            FileTools(security=container.get("security")),
            TaskTools(security=container.get("security")),
            MemoryTools(memory=container.get("memory"), security=container.get("security")),
            TaskPlannerTools(memory=container.get("memory")),
            VerificationTools(verification=container.get("verification"), security=container.get("security")),
            VisionTools(security=container.get("security")),
        ] + skills_list

        container._services["tools"] = tools_base
    except Exception as e:
        print(f"FAILED to build container: {e}")
        sys.exit(1)

    print("\n[2] Eagerly starting container services...")
    try:
        await container.startup()
        print("-> Container services started successfully.")
    except Exception as e:
        print(f"FAILED during container startup: {e}")
        sys.exit(1)

    # All 13 agents to test
    agents_to_test = [
        "memory_agent",
        "supervisor_agent",
        "planning_agent",
        "execution_agent",
        "coordinator_agent",
        "coding_agent",
        "debugging_agent",
        "browser_agent",
        "vision_agent",
        "verification_agent",
        "recovery_agent",
        "integration_agent",
        "interaction_agent"
    ]

    agent_bus = container.get("agent_bus")
    if not agent_bus:
        print("FAILED: agent_bus not found in ServiceContainer.")
        sys.exit(1)

    # Make sure they are all loaded in container to register on the bus
    print("\n[3] Instantiating and registering agents...")
    for agent_id in agents_to_test:
        try:
            container.get(agent_id)
            print(f"-> Eagerly booted and registered: {agent_id}")
        except Exception as e:
            print(f"FAILED to boot agent {agent_id}: {e}")
            sys.exit(1)

    print("\n[4] Dispatching health_check to each agent via AgentBus...")
    print(f"{'Agent ID':<25} | {'Status':<10} | {'Latency (ms)':<12} | {'Response/Error'}")
    print("-" * 75)

    all_passed = True
    results_summary = []

    for agent_id in agents_to_test:
        task_id = str(uuid.uuid4())
        task = AgentTask(
            task_id=task_id,
            task_type="health_check",
            payload={},
            origin_agent="smoke_test_runner",
            target_agent=agent_id
        )

        start_time = time.perf_counter()
        try:
            res = await agent_bus.dispatch(task, timeout=5.0)
            duration_ms = (time.perf_counter() - start_time) * 1000
            
            if res.success:
                status_str = "PASS"
                detail = res.result
            else:
                status_str = "FAIL"
                detail = res.error or "Unknown error"
                all_passed = False
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            status_str = "FAIL"
            detail = str(e)
            all_passed = False

        print(f"{agent_id:<25} | {status_str:<10} | {duration_ms:<12.2f} | {detail}")
        results_summary.append((agent_id, status_str, duration_ms, detail))

    print("\n[5] Tearing down container...")
    await container.shutdown()
    print("-> Container teardown complete.")

    print("\n--------------------------------------------------")
    if all_passed:
        print("RESULT: ALL 13 AGENTS ARE INTENTIONAL AND REACHABLE! (SMOKE TEST PASSED)")
        print("--------------------------------------------------")
        sys.exit(0)
    else:
        print("RESULT: SMOKE TEST FAILED (One or more agents unreachable/unresponsive)")
        print("--------------------------------------------------")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
