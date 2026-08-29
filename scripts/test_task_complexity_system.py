"""
================================================================================
JARVIS UNIFIED TASK COMPLEXITY & CLASSIFICATION TESTING SUITE
================================================================================
Comprehensive QA and Automated Validation System testing all levels of task
classification, scoring, compound decomposition, and treatment pipelines
(Express Lane vs Deep Swarm Lane).

Can be executed directly via:
    python scripts/test_task_complexity_system.py
or via pytest:
    pytest apps/backend/tests/test_unified_complexity_system.py -v
================================================================================
"""

import sys
import os
import time
import asyncio
from typing import List, Dict, Any

# Ensure backend path is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())

import pytest
from modules.routing.task_classifier import (
    TaskClassifier,
    TaskComplexityLevel,
    TaskExecutionLane,
    TaskClassificationReport,
)
from modules.routing.intent_router import IntentRouter, QueryIntent, IntentClassificationResult
from modules.planning.task_planner import TaskPlannerTools
from ai.agents.types import AgentTask, AgentResult


# ==============================================================================
# SUITE 1: COMPREHENSIVE CLASSIFICATION & TAXONOMY VALIDATION
# ==============================================================================

class TestClassificationTaxonomy:
    """Validates classification precision across all 6 taxonomy levels (0 through 5)."""

    def test_level_0_conversational_english(self):
        prompts = [
            "Hello Jarvis",
            "Hey buddy, how are you?",
            "Good morning assistant!",
            "Who created you?",
            "Thank you so much Jarvis",
            "Goodbye, see you later",
        ]
        for p in prompts:
            report = TaskClassifier.classify(p)
            assert report.complexity_level == TaskComplexityLevel.LEVEL_0_CONVERSATIONAL, f"Failed for: '{p}'"
            assert report.is_complex is False, f"Expected non-complex for: '{p}'"
            assert report.is_direct_chat is True, f"Expected direct chat for: '{p}'"
            assert report.execution_lane == TaskExecutionLane.EXPRESS_CHAT, f"Expected EXPRESS_CHAT for: '{p}'"
            assert report.complexity_score <= 0.25, f"Score too high ({report.complexity_score}) for: '{p}'"

    def test_level_0_conversational_hinglish(self):
        prompts = [
            "Namaste Jarvis",
            "Kaise ho bhai?",
            "Kya haal hai Jarvis?",
            "Tum kaun ho?",
            "Dhanyawad Jarvis",
            "Shukriya",
        ]
        for p in prompts:
            report = TaskClassifier.classify(p)
            assert report.complexity_level == TaskComplexityLevel.LEVEL_0_CONVERSATIONAL, f"Failed for: '{p}'"
            assert report.is_complex is False
            assert report.is_direct_chat is True
            assert report.execution_lane == TaskExecutionLane.EXPRESS_CHAT

    def test_level_0_informational_qa(self):
        prompts = [
            "What is quantum entanglement?",
            "Explain how neural networks learn",
            "Why is the sky blue during the day?",
            "Who discovered gravity?",
            "Calculate 25 * 14 + 100",
            "Write a short haiku about coding",
        ]
        for p in prompts:
            report = TaskClassifier.classify(p)
            assert report.complexity_level == TaskComplexityLevel.LEVEL_0_CONVERSATIONAL, f"Failed for: '{p}'"
            assert report.is_complex is False
            assert report.is_direct_chat is True
            assert report.primary_intent == "informational_qa"
            assert report.execution_lane == TaskExecutionLane.EXPRESS_CHAT

    def test_level_1_memory_inquiries(self):
        prompts = [
            "What do you know about me?",
            "What do you remember about my previous work?",
            "Who am I and what is my name?",
            "What were we discussing yesterday in our last session?",
            "Tell me everything about me and my preferences",
        ]
        for p in prompts:
            report = TaskClassifier.classify(p)
            assert report.complexity_level == TaskComplexityLevel.LEVEL_1_MEMORY, f"Failed for: '{p}'"
            assert report.is_complex is False
            assert report.is_direct_chat is True
            assert report.execution_lane == TaskExecutionLane.EXPRESS_MEMORY
            assert "memory_agent" in report.target_agents

    def test_level_2_atomic_system_actions(self):
        test_cases = [
            ("set volume to 70%", "set_volume", {"level": 70}),
            ("mute system volume", "mute_audio", {}),
            ("unmute audio", "unmute_audio", {}),
            ("set display brightness to 80%", "set_brightness", {"level": 80}),
            ("take a screenshot", "take_screenshot", {}),
            ("open settings", "open_settings", {}),
            ("open chrome", "open_application", {"app_name": "chrome"}),
            ("launch notepad", "open_application", {"app_name": "notepad"}),
            ("open https://github.com", "open_url", {"url": "https://github.com"}),
            ("open youtube", "open_url", {"url": "https://www.youtube.com"}),
            ("play interstellar theme on youtube", "play_youtube", {"query": "interstellar theme"}),
            ("search google for asyncio event loop", "search_google", {"query": "asyncio event loop"}),
            ("check my unread emails on gmail", "read_social_messages", {"platform": "gmail", "contact": "", "filter": "unread"}),
            ("check unread whatsapp", "read_social_messages", {"platform": "whatsapp", "contact": "", "filter": "unread"}),
        ]
        for prompt, expected_tool, expected_params in test_cases:
            report = TaskClassifier.classify(prompt)
            assert report.complexity_level == TaskComplexityLevel.LEVEL_2_SINGLE_ACTION, f"Failed level for: '{prompt}'"
            assert report.is_complex is False, f"Expected non-complex for: '{prompt}'"
            assert report.is_direct_chat is False, f"Expected tool action for: '{prompt}'"
            assert report.execution_lane == TaskExecutionLane.EXPRESS_TOOL, f"Expected EXPRESS_TOOL for: '{prompt}'"
            assert report.suggested_tool == expected_tool, f"Expected tool {expected_tool}, got {report.suggested_tool}"
            assert report.extracted_params == expected_params, f"Params mismatch for '{prompt}': {report.extracted_params}"
            assert report.fast_subtasks is not None, f"Fast subtasks missing for '{prompt}'"
            assert len(report.fast_subtasks) == 1

    def test_level_3_multistep_domain_workflows(self):
        prompts = [
            "Find all error log files in D:\\Logs and delete old ones",
            "Search my local directory for all python files and format them",
            "Download the latest release zip and extract it to D:\\workspace",
        ]
        for p in prompts:
            report = TaskClassifier.classify(p)
            assert report.is_complex is True, f"Expected complex for: '{p}'"
            assert report.complexity_score >= 0.35, f"Score too low for: '{p}'"
            assert report.execution_lane in (TaskExecutionLane.STANDARD_DAG, TaskExecutionLane.SWARM_ORCHESTRATION)

    def test_level_4_multi_agent_swarm(self):
        prompts = [
            "Research CBDC implementations in Europe, synthesize a comparison table, and save to report.md",
            "Analyze the market cap of top 5 AI companies, compile a summary report, and email it to my team",
            "Search for latest LLM benchmarks, download the paper, extract figures, and create a summary markdown",
        ]
        for p in prompts:
            report = TaskClassifier.classify(p)
            assert report.is_complex is True, f"Expected complex for: '{p}'"
            assert report.complexity_score >= 0.50, f"Score too low ({report.complexity_score}) for: '{p}'"
            assert report.complexity_level in (TaskComplexityLevel.LEVEL_4_MULTI_AGENT_SWARM, TaskComplexityLevel.LEVEL_5_DEEP_PROJECT)
            assert report.execution_lane == TaskExecutionLane.SWARM_ORCHESTRATION
            assert "planning_agent" in report.target_agents

    def test_level_5_deep_projects_and_grounded_vision(self):
        # Deep Full-Stack Development
        code_prompt = "Build a full stack React hotel booking app with FastAPI backend and SQLite database"
        report_code = TaskClassifier.classify(code_prompt)
        assert report_code.is_complex is True
        assert report_code.complexity_level == TaskComplexityLevel.LEVEL_5_DEEP_PROJECT
        assert report_code.complexity_score >= 0.70
        assert "coding_agent" in report_code.target_agents

        # Grounded Vision / UI Navigation
        vision_prompts = [
            "Click on the 2nd blue button on the screen",
            "Look at the screen, find the download button on the invoice, and click it",
            "Scroll until the submit form is visible, then tap on the checkbox",
            "Choose the cheapest flight option displayed on the monitor",
        ]
        for vp in vision_prompts:
            report_vis = TaskClassifier.classify(vp)
            assert report_vis.is_complex is True, f"Expected complex for: '{vp}'"
            assert report_vis.requires_grounded_vision is True, f"Expected vision required for: '{vp}'"
            assert report_vis.execution_lane == TaskExecutionLane.GROUNDED_PROJECT
            assert "vision_agent" in report_vis.target_agents

    def test_destructive_risk_and_verification_safeguards(self):
        destructive_prompts = [
            "Delete all user records from database and drop tables",
            "Format drive D: and remove all system files",
            "Kill all running python processes and unlink logs",
            "Git reset --hard HEAD~5 and git clean -fd",
        ]
        for dp in destructive_prompts:
            report = TaskClassifier.classify(dp)
            assert report.risk_level == "high", f"Expected high risk for: '{dp}'"
            assert report.requires_verification is True, f"Expected verification enforced for: '{dp}'"
            assert report.is_complex is True, f"Expected destructive command to be routed through swarm for: '{dp}'"


# ==============================================================================
# SUITE 2: COMPOUND INTENT DECOMPOSITION VALIDATION
# ==============================================================================

class TestCompoundDecomposition:
    """Validates multi-clause and multi-goal request splitting."""

    def test_conjunction_splitting(self):
        compound = "Open Chrome and search for latest AI news and then take a screenshot of the results"
        goals = TaskClassifier.decompose_intents(compound)
        assert len(goals) == 3
        assert any("chrome" in g.lower() for g in goals)
        assert any("search" in g.lower() for g in goals)
        assert any("screenshot" in g.lower() for g in goals)

    def test_while_and_after_that_splitting(self):
        compound = "Compile the backend code while downloading the frontend dependencies. In addition, run unit tests."
        goals = TaskClassifier.decompose_intents(compound)
        assert len(goals) >= 2

    def test_single_intent_passthrough(self):
        single = "What is the capital of France?"
        goals = TaskClassifier.decompose_intents(single)
        assert len(goals) == 1
        assert goals[0] == single


# ==============================================================================
# SUITE 3: TREATMENT PIPELINE SIMULATION (EXPRESS LANE VS SWARM LANE)
# ==============================================================================

class MockBus:
    """Mock agent bus tracking dispatches and performance for QA testing."""
    def __init__(self):
        self.dispatched_tasks: List[AgentTask] = []
        self.call_counts: Dict[str, int] = {}
        self.handlers: Dict[str, Any] = {}

    def register(self, agent_id: str, handler):
        self.handlers[agent_id] = handler

    async def dispatch(self, task: AgentTask, timeout_seconds: float = 30.0) -> AgentResult:
        self.dispatched_tasks.append(task)
        self.call_counts[task.target_agent] = self.call_counts.get(task.target_agent, 0) + 1
        
        # Simulate agent response based on task_type
        if task.task_type == "generate_context":
            return AgentResult(
                task_id=task.task_id,
                success=True,
                result={"context": "Mocked context from memory and tools"}
            )
        elif task.task_type == "create_plan":
            return AgentResult(
                task_id=task.task_id,
                success=True,
                result={"plan": [{"id": 1, "description": "Step 1", "tool_name": "execute_command", "args": {}}]}
            )
        elif task.task_type == "evaluate_plan":
            return AgentResult(
                task_id=task.task_id,
                success=True,
                result={"evaluation": "Plan accepted by Quality Gate."}
            )
        elif task.task_type == "execute_plan":
            return AgentResult(
                task_id=task.task_id,
                success=True,
                result={"status": "executed", "output": "Execution successful"}
            )
        elif task.task_type == "speak":
            return AgentResult(task_id=task.task_id, success=True)
        
        return AgentResult(task_id=task.task_id, success=True, result={})


class TestExpressVsSwarmTreatment:
    """Verifies that Normal tasks execute with zero overhead and Complex tasks run full swarm."""

    @pytest.mark.asyncio
    async def test_normal_task_express_lane_treatment(self):
        """A normal single-step task (e.g. 'set volume to 50%') should NOT invoke planning or context agents."""
        from ai.agents.coordinator.agent import CoordinatorAgent

        bus = MockBus()
        coordinator = CoordinatorAgent(bus=bus, available_agents=["execution_agent", "planning_agent"])

        task = AgentTask(
            task_id="test_normal_1",
            task_type="execute_goal",
            payload={"goal": "set volume to 50%"},
            origin_agent="supervisor_agent",
            target_agent="coordinator_agent"
        )

        res = await coordinator.handle(task)
        assert res.success is True
        assert res.result.get("status") == "completed"

        # Assert zero planning_agent calls! (Express lane directly calls execution_agent)
        assert bus.call_counts.get("planning_agent", 0) == 0
        assert bus.call_counts.get("execution_agent", 0) == 1

    @pytest.mark.asyncio
    async def test_complex_task_swarm_lane_treatment(self):
        """A complex task (e.g. 'Build React app and deploy') MUST trigger the full multi-agent swarm cycle."""
        from ai.agents.coordinator.agent import CoordinatorAgent

        bus = MockBus()
        coordinator = CoordinatorAgent(bus=bus, available_agents=["execution_agent", "planning_agent"])

        task = AgentTask(
            task_id="test_complex_1",
            task_type="execute_goal",
            payload={"goal": "Build a full stack React app and test all endpoints"},
            origin_agent="supervisor_agent",
            target_agent="coordinator_agent"
        )

        res = await coordinator.handle(task)
        assert res.success is True

        # Assert full multi-agent swarm pipeline was invoked!
        assert bus.call_counts.get("planning_agent", 0) >= 1, "Planning agent should have been called"
        assert bus.call_counts.get("execution_agent", 0) >= 1, "Execution agent should have been called"


# ==============================================================================
# SUITE 4: BENCHMARK & PERFORMANCE LATENCY
# ==============================================================================

class TestPerformanceAndLatency:
    """Benchmarking to ensure classification engine performs under 1ms per decision."""

    def test_classification_latency_benchmark(self):
        queries = [
            "Hello Jarvis",
            "What do you know about me?",
            "Set volume to 60%",
            "Open Chrome and navigate to github.com",
            "Research CBDC adoption across 10 central banks and compile a detailed markdown report",
            "Build a full stack React hotel booking application with FastAPI backend and unit tests",
            "Click on the 2nd blue button on the screen",
            "Delete all old log files and format disk",
        ]

        iterations = 50
        start_t = time.perf_counter()
        for _ in range(iterations):
            for q in queries:
                TaskClassifier.classify(q)
        end_t = time.perf_counter()

        total_ops = len(queries) * iterations
        total_time_ms = (end_t - start_t) * 1000
        avg_time_per_op_ms = total_time_ms / total_ops

        print(f"\n[BENCHMARK] Executed {total_ops} classifications in {total_time_ms:.2f}ms (Avg: {avg_time_per_op_ms:.4f}ms per query)")
        assert avg_time_per_op_ms < 1.0, f"Classification too slow: {avg_time_per_op_ms:.4f}ms per query"


# ==============================================================================
# STANDALONE CLI TEST RUNNER & DIAGNOSTIC REPORT
# ==============================================================================

def run_all_qa_tests():
    print("=" * 80)
    print("   JARVIS TASK COMPLEXITY & TREATMENT QA VALIDATION RUNNER")
    print("=" * 80)
    
    suite_names = [
        ("Suite 1: Classification Taxonomy (Levels 0-5)", TestClassificationTaxonomy),
        ("Suite 2: Compound Intent Decomposition", TestCompoundDecomposition),
        ("Suite 3: Express Lane vs Deep Swarm Treatment", TestExpressVsSwarmTreatment),
        ("Suite 4: Performance & Sub-Millisecond Latency", TestPerformanceAndLatency),
    ]

    total_passed = 0
    total_failed = 0

    for name, suite_cls in suite_names:
        print(f"\n[*] Running: {name}...")
        instance = suite_cls()
        methods = [m for m in dir(instance) if m.startswith("test_")]

        for method_name in methods:
            func = getattr(instance, method_name)
            try:
                if asyncio.iscoroutinefunction(func):
                    asyncio.run(func())
                else:
                    func()
                print(f"    [PASSED] {method_name}")
                total_passed += 1
            except Exception as e:
                print(f"    [FAILED] {method_name} -> {e}")
                total_failed += 1

    print("\n" + "=" * 80)
    print(f"QA TEST SUMMARY: {total_passed} PASSED, {total_failed} FAILED (Total: {total_passed + total_failed})")
    print("=" * 80)

    if total_failed > 0:
        sys.exit(1)
    else:
        print("[SUCCESS] All task classification and treatment suites verified perfectly!\n")


if __name__ == "__main__":
    run_all_qa_tests()
