"""
scripts/test_all_agents.py — Unified All-Agent Verification Test Suite for JARVIS.

Tests 100% of all 24 agents in the JARVIS Multi-Agent Architecture:
1. SupervisorAgent
2. CoordinatorAgent
3. PlanningAgent
4. ExecutionAgent
5. CodingAgent
6. DebuggingAgent
7. BrowserAgent
8. VisionAgent
9. VerificationAgent
10. RecoveryAgent
11. IntegrationAgent
12. InteractionAgent
13. LanguageAgent
14. DeepResearchAgent
15. LearningAgent
16. MemoryAgent
17. UIUXDesignerAgent
18. SocialMediaAgent
19. WhatsAppAgent
20. GmailAgent
21. InstagramAgent
22. SocialWatcher
23. FileDiscoveryAgent
24. VoiceListenerPipeline
"""
import os
import sys
import time
import asyncio
import uuid
from typing import Dict, Any, List

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure backend root is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from config.settings import load_config
load_config()

from container import build_container, ServiceContainer
from ai.contracts import AgentTask, AgentResult


async def run_all_agent_tests():
    print("=" * 80)
    print("  JARVIS ALL-AGENT VERIFICATION HARNESS (24 AGENTS COVERAGE)")
    print("=" * 80)
    print()

    # 1. Initialize container
    print("[+] Initializing ServiceContainer and booting dependencies...")
    container = build_container()
    
    # Load and cache tools base
    from modules.skills.registry import SkillRegistry
    from tools.builtin import (
        SystemTools, WindowTools, AppTools, BrowserTools, MediaTools,
        KeyboardTools, MouseTools, FileTools, TaskTools, MemoryTools,
        VerificationTools, VisionTools
    )
    from modules.planning.task_planner import TaskPlannerTools

    skill_reg = SkillRegistry(
        memory=container.get("memory"),
        security=container.get("security"),
        room=None,
        verification=container.get("verification"),
    )
    skills_list = skill_reg.load_skills()

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
    print("-> ServiceContainer successfully initialized.\n")

    bus = container.get("agent_bus")

    # 2. Agent definitions to test
    agents_inventory = [
        ("SupervisorAgent", "supervisor_agent", "Central orchestration, routing, speech queue"),
        ("CoordinatorAgent", "coordinator_agent", "Subtask routing, context compilation, goal execution"),
        ("PlanningAgent", "planning_agent", "DAG plan generation, replanning, tool selection"),
        ("ExecutionAgent", "execution_agent", "Subtask execution, dependency DAGs, recovery dispatch"),
        ("CodingAgent", "coding_agent", "Code writing, AST refactoring, test generation"),
        ("DebuggingAgent", "debugging_agent", "Error diagnosis, self-healing sequences, fix verification"),
        ("BrowserAgent", "browser_agent", "Web automation, DOM structure analysis, browser control"),
        ("VisionAgent", "vision_agent", "Screen analysis, ordinal UI element localization, OCR"),
        ("VerificationAgent", "verification_agent", "Quality gating, execution output verification"),
        ("RecoveryAgent", "recovery_agent", "Failure pattern recovery, streak tracking, lessons lookup"),
        ("IntegrationAgent", "integration_agent", "API calling, webhooks, SSRF safety, third-party sync"),
        ("InteractionAgent", "interaction_agent", "Grounded interaction loops, perceptual action validation"),
        ("LanguageAgent", "language_agent", "Language detection, multilingual translation, document extraction"),
        ("DeepResearchAgent", "deep_research_agent", "Multi-source research, fact validation, citation synthesis"),
        ("LearningAgent", "learning_agent", "Self-learning loops, capability scoring, curriculum generation"),
        ("MemoryAgent", "memory_agent", "Context retrieval, workflow search, memory lifecycle compression"),
        ("UIUXDesignerAgent", "ui_ux_agent", "WCAG mathematical contrast, design tokens, prototypes"),
        ("SocialMediaAgent", "social_media_agent", "Multi-channel social orchestration, adapter dispatching"),
        ("WhatsAppAgent", "whatsapp_agent", "Inbound WhatsApp processing, auto-reply, business tool routing"),
        ("GmailAgent", "gmail_agent", "Email inbox triage, contextual drafts, followup scheduling"),
        ("InstagramAgent", "instagram_agent", "Trend research, content generation, competitor auditing"),
        ("SocialWatcher", "social_watcher", "Continuous social feed monitoring and background polling"),
        ("FileDiscoveryAgent", "file_discovery_agent", "Workspace file indexing, semantic discovery"),
        ("VoiceListenerPipeline", "voice_listener", "Non-blocking continuous voice input queue & STT publishing"),
    ]

    results_table = []
    passed_count = 0
    failed_count = 0

    print("[+] Running verification across all 24 agents...")
    print("-" * 80)

    for idx, (class_name, agent_key, desc) in enumerate(agents_inventory, 1):
        t0 = time.perf_counter()
        status = "PASSED"
        err_msg = ""
        
        try:
            agent_obj = container.get_or_none(agent_key)
            if agent_obj is None:
                raise RuntimeError(f"Agent '{agent_key}' not found or failed in ServiceContainer.")

            # Test specific agent mechanisms
            if hasattr(agent_obj, "handle"):
                # Dispatch health check task
                hc_task = AgentTask(
                    task_id=f"hc_{agent_key}_{uuid.uuid4().hex[:6]}",
                    task_type="health_check",
                    target_agent=agent_key
                )
                res = await agent_obj.handle(hc_task)
                if not res.success:
                    raise RuntimeError(f"Health check failed: {res.error}")

            # Additional agent-specific verification
            if agent_key == "supervisor_agent":
                speak_task = AgentTask(task_id="t_spk", task_type="speak", payload={"text": "All agents verified.", "priority": "normal"})
                spk_res = await agent_obj.handle(speak_task)
                assert spk_res.success is True

            elif agent_key == "language_agent":
                det_task = AgentTask(task_id="t_det", task_type="detect_language", payload={"text": "Namaste Bharat"})
                det_res = await agent_obj.handle(det_task)
                assert det_res.success is True

            elif agent_key == "ui_ux_agent":
                wcag_task = AgentTask(task_id="t_wcag", task_type="calculate_contrast", payload={"foreground": "#FFFFFF", "background": "#000000"})
                wcag_res = await agent_obj.handle(wcag_task)
                assert wcag_res.success is True

            elif agent_key == "voice_listener":
                await agent_obj.push_transcript("jarvis status check", is_final=True)
                assert not agent_obj._input_queue.empty()
                _ = await agent_obj._input_queue.get()

        except Exception as e:
            status = "FAILED"
            err_msg = str(e)
            failed_count += 1
        else:
            passed_count += 1

        elapsed = (time.perf_counter() - t0) * 1000
        results_table.append({
            "index": idx,
            "name": class_name,
            "key": agent_key,
            "status": status,
            "elapsed_ms": elapsed,
            "error": err_msg,
            "description": desc
        })
        
        status_symbol = "[PASS]" if status == "PASSED" else "[FAIL]"
        print(f"[{idx:02d}/24] {status_symbol} {class_name:<22} ({agent_key}) - {elapsed:.1f}ms")
        if err_msg:
            print(f"       Error: {err_msg}")

    print("-" * 80)
    print(f"\n[=] RESULTS: {passed_count}/24 Agents Passed ({passed_count/24*100:.1f}%), {failed_count} Failed.")
    print("=" * 80)

    # Teardown
    await container.shutdown()

    if failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all_agent_tests())
