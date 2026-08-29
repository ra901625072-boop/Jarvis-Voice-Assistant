import asyncio
import sys
import os
import time
import uuid
import argparse
import logging

# Adjust path to find modules inside apps/backend
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "backend"))
sys.path.insert(0, backend_dir)

from config.settings import load_config
load_config()

from container import build_container
from ai.agents.types import AgentTask, AgentResult

def setup_logging():
    # Clear existing handlers on the root logger
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    formatter = logging.Formatter("[%(asctime)s] %(name)s - %(levelname)s: %(message)s")
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    
    # Set levels
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(stdout_handler)
    
    # Silence extremely noisy third-party loggers
    noisy_loggers = [
        "h2",
        "hickory_net",
        "hickory_resolver",
        "rustls",
        "hyper_util",
        "reqwest",
        "primp",
        "cookie_store",
        "duckduckgo_search",
        "livekit.plugins.google",
        "urllib3",
        "google",
        "google_genai",
        "httpcore",
        "httpx",
    ]
    for n_logger in noisy_loggers:
        if n_logger in ("google_genai", "google", "h2", "primp", "cookie_store"):
            logging.getLogger(n_logger).setLevel(logging.ERROR)
        else:
            logging.getLogger(n_logger).setLevel(logging.WARNING)

class AutoApprovalStore:
    def request(self, task_id: str, agent_id: str, action: str,
                category: str, payload: dict, timeout: float = 120.0) -> str:
        return "auto_approved"

    async def wait_for_approval(self, approval_id: str, timeout: float = 120.0) -> tuple[bool, str]:
        return True, "Auto-approved in headless training mode."

async def main():
    parser = argparse.ArgumentParser(description="Run a custom goal unmocked on JARVIS.")
    parser.add_argument("goal", type=str, help="The goal description to run.")
    args = parser.parse_args()

    print(f"Running in UNMOCKED mode. Live API calls will be made.")
    setup_logging()
    
    print("\n[1] Starting container services...")
    container = build_container()
    container._services["approval_store"] = AutoApprovalStore()
    
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

    await container.startup()
    
    # Eagerly load all agents
    agents = [
        "memory_agent", "supervisor_agent", "planning_agent", 
        "execution_agent", "coordinator_agent", "coding_agent", 
        "debugging_agent", "browser_agent", "vision_agent", 
        "verification_agent", "recovery_agent", "integration_agent", 
        "interaction_agent"
    ]
    for agent_id in agents:
        container.get(agent_id)
        
    bus = container.get("agent_bus")
    
    print(f"\n[2] Dispatching goal: '{args.goal}' to coordinator...")
    task_id = str(uuid.uuid4())
    task = AgentTask(
        task_id=task_id,
        task_type="execute_goal",
        payload={"goal": args.goal},
        origin_agent="cli_runner",
        target_agent="coordinator_agent"
    )
    
    start_time = time.perf_counter()
    try:
        res = await bus.dispatch(task, timeout=600.0)
        duration = (time.perf_counter() - start_time) * 1000
        print("\n==================================================")
        print("EXECUTION RESULT")
        print("==================================================")
        print(f"Goal:        {args.goal}")
        print(f"Success:     {res.success}")
        print(f"Duration:    {duration/1000:.2f}s")
        print(f"Tokens Used: {res.tokens_used}")
        print(f"Cost USD:    ${res.cost_usd:.5f}")
        if res.success:
            print(f"Result:      {res.result}")
        else:
            print(f"Error:       {res.error}")
        print("==================================================")
    except Exception as e:
        print(f"\nCRASHED with error: {e}")
        
    print("\n[3] Tearing down container...")
    await container.shutdown()
    print("-> Container teardown complete.")

if __name__ == "__main__":
    asyncio.run(main())
