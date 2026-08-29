"""
test_learning_system.py
-----------------------
Unit & integration test suite for JARVIS Real Learning Agent:
- Trajectory & Episode Collection
- Multi-Dimensional Evaluation Engine
- Causal Failure & Invariant Analysis
- Memory Consolidation & Tiered Strategy Promotion
- Skill Synthesis & AST Safety Validation
- LearningAgent Handlers & Context Injection
"""

import pytest
import json
import uuid
from ai.agents.types import AgentTask
from modules.bus.redis_bus import RedisBus
from ai.agents.learning.agent import LearningAgent
from modules.learning.trajectory_collector import TrajectoryCollector
from modules.learning.evaluator_engine import EvaluatorEngine
from modules.learning.root_cause_analyzer import RootCauseAnalyzer
from modules.learning.memory_consolidator import MemoryConsolidator
from modules.learning.skill_synthesizer import SkillSynthesizer
from modules.learning.realtime_learner import RealtimeLearner


class TestTrajectoryCollector:
    def test_trajectory_recording_and_persistence(self, memory_manager):
        collector = TrajectoryCollector(
            agent_id="coding_agent",
            task_type="write_code",
            goal="Create FastAPI health endpoint",
            context={"project": "backend"}
        )
        collector.set_plan([
            {"step": 1, "action": "create_file"},
            {"step": 2, "action": "run_test"}
        ])

        # Step 1: tool call
        collector.add_step(
            action="filesystem.create_file",
            tool_name="write_to_file",
            args={"path": "main.py"},
            observation="File written successfully",
            thought="Creating entrypoint"
        )
        # Step 2: verify
        collector.add_step(
            action="system.run_test",
            tool_name="pytest",
            args={"path": "tests/test_main.py"},
            observation="1 passed",
            thought="Tests passing"
        )

        collector.finalize(
            success=True,
            result={"status": "completed"},
            duration_ms=450.0,
            tokens_used=1200,
            cost_usd=0.002
        )

        ep_id = collector.save_to_db(memory_manager)
        assert ep_id is not None

        # Fetch from DB
        fetched = TrajectoryCollector.get_episode(memory_manager, ep_id)
        assert fetched is not None
        assert fetched["agent_id"] == "coding_agent"
        assert fetched["task_type"] == "write_code"
        assert len(fetched["trajectory"]) == 2
        assert fetched["success"] is True

        # Fetch recent
        recent = TrajectoryCollector.get_recent_episodes(memory_manager, agent_id="coding_agent", limit=5)
        assert len(recent) >= 1
        assert recent[0]["episode_id"] == ep_id


class TestEvaluatorAndRootCause:
    def test_multi_dimensional_evaluator_success(self):
        evaluator = EvaluatorEngine()
        episode = {
            "success": True,
            "duration_ms": 1500.0,
            "tokens_used": 1500,
            "trajectory": [
                {"action": "browser.navigate", "error": None},
                {"action": "browser.extract", "error": None}
            ],
            "outcome": {"error": None}
        }
        score = evaluator.evaluate_episode(episode)
        assert score["success"] is True
        assert score["quality"] == 1.0
        assert score["safety"] == 1.0
        assert score["overall_utility"] >= 0.80

    def test_multi_dimensional_evaluator_failure(self):
        evaluator = EvaluatorEngine()
        episode = {
            "success": False,
            "duration_ms": 12000.0,
            "tokens_used": 9000,
            "trajectory": [
                {"action": "browser.click", "error": "TimeoutException"}
            ],
            "outcome": {"error": "TimeoutException: element not clickable"}
        }
        score = evaluator.evaluate_episode(episode)
        assert score["success"] is False
        assert score["quality"] <= 0.2
        assert score["overall_utility"] < 0.50

    def test_root_cause_analysis_and_invariants(self):
        analyzer = RootCauseAnalyzer()

        # Invariant breach
        inv_episode = {
            "agent_id": "execution_agent",
            "task_type": "cleanup",
            "outcome": {"error": "Cannot terminate daemon server process: invariant violated"}
        }
        res_inv = analyzer.analyze(inv_episode)
        assert res_inv["root_cause_category"] == "invariant_violation"
        assert res_inv["invariant_rule"] is not None

        # Timeout
        timeout_episode = {
            "agent_id": "browser_agent",
            "task_type": "fetch_page",
            "outcome": {"error": "Connection timed out after 30000ms"}
        }
        res_timeout = analyzer.analyze(timeout_episode)
        assert res_timeout["root_cause_category"] == "timeout_or_latency_error"


class TestMemoryConsolidatorAndLifecycle:
    def test_consolidation_and_strategy_promotion(self, memory_manager):
        consolidator = MemoryConsolidator(memory_manager)

        # Seed 3 matching failure episodes to trigger consolidation
        for i in range(3):
            col = TrajectoryCollector(
                agent_id="browser_agent",
                task_type="scrape_data",
                goal=f"Scrape attempt {i}",
                episode_id=f"ep_test_fail_{i}"
            )
            col.add_step(action="browser.navigate", error="Cloudflare captcha challenge detected")
            col.finalize(success=False, error="Cloudflare captcha challenge detected", duration_ms=2000.0)
            col.save_to_db(memory_manager)

        # Seed 3 matching success episodes
        for i in range(3):
            col = TrajectoryCollector(
                agent_id="coding_agent",
                task_type="lint_check",
                goal=f"Lint check {i}",
                episode_id=f"ep_test_succ_{i}"
            )
            col.add_step(action="run_linter", observation="0 errors")
            col.finalize(success=True, result="Clean code", duration_ms=500.0)
            col.save_to_db(memory_manager)

        summary = consolidator.consolidate_episodes(min_cluster_size=2)
        assert summary["strategies_created"] >= 1

        # Check strategies stored in DB
        active = consolidator.get_active_strategies(min_status="validated")
        assert len(active) >= 1

        strat = active[0]
        assert strat["utility_score"] > 0.0

        # Test promotion
        promoted = consolidator.promote_strategy(strat["id"], "trusted", reason="Benchmark testing passed")
        assert promoted is True


class TestSkillSynthesizerAndAST:
    def test_ast_safety_checker(self, memory_manager):
        synthesizer = SkillSynthesizer(memory_manager)

        safe_code = """
import os
import json

class SafeSkill:
    def run(self):
        return {"status": "ok"}
"""
        res_safe = synthesizer.validate_code_safety(safe_code)
        assert res_safe["safe"] is True

        unsafe_code = """
import os
def hack():
    os.system("rm -rf /")
    eval("1+1")
"""
        res_unsafe = synthesizer.validate_code_safety(unsafe_code)
        assert res_unsafe["safe"] is False
        assert "Forbidden" in res_unsafe["error"]

    def test_skill_generation_from_strategy(self, memory_manager):
        consolidator = MemoryConsolidator(memory_manager)
        synthesizer = SkillSynthesizer(memory_manager)

        # Create a test strategy
        strat_id = None
        ts = "2026-08-29T20:00:00"
        with memory_manager._lock:
            cur = memory_manager.dbs["conversations"].execute(
                """INSERT INTO strategies (name, category, description, trigger_condition, action_guidance, confidence, utility_score, status, created_at, updated_at)
                   VALUES ('deploy_fastapi', 'devops', 'Deploy FastAPI to server', 'deploy fastapi', '1. check env 2. run uvicorn', 0.9, 0.8, 'validated', ?, ?)""",
                (ts, ts)
            )
            strat_id = cur.lastrowid
            memory_manager.dbs["conversations"].commit()

        candidate_id = synthesizer.create_skill_candidate(strat_id)
        assert candidate_id is not None

        distilled = synthesizer.test_and_distill_skill(candidate_id)
        assert distilled is True


class TestLearningAgentIntegration:
    @pytest.mark.asyncio
    async def test_learning_agent_end_to_end(self, memory_manager):
        bus = RedisBus()
        agent = LearningAgent(bus, memory=memory_manager)

        # 1. Health check
        hc = await agent.handle(AgentTask(task_type="health_check"))
        assert hc.success is True

        # 2. Record episode via RealtimeLearner
        rl = RealtimeLearner(memory_manager)
        rl.process(
            agent_id="research_agent",
            task_type="web_search",
            task_id="ep_test_live_1",
            success=True,
            error_summary=None,
            goal_hint="Investigate quantum state",
            duration_ms=800.0
        )

        # 3. Evaluate episode via LearningAgent
        eval_task = AgentTask(
            task_type="evaluate_episode",
            payload={"episode_id": "ep_test_live_1"}
        )
        eval_res = await agent.handle(eval_task)
        assert eval_res.success is True
        assert eval_res.result["quality"] == 1.0

        # 4. Consolidate memories via LearningAgent
        cons_task = AgentTask(
            task_type="consolidate_memories",
            payload={"min_cluster_size": 1}
        )
        cons_res = await agent.handle(cons_task)
        assert cons_res.success is True

        # 5. Get active strategies via LearningAgent
        strat_task = AgentTask(
            task_type="get_active_strategies",
            payload={"min_status": "candidate"}
        )
        strat_res = await agent.handle(strat_task)
        assert strat_res.success is True
        assert "strategies" in strat_res.result

        # 6. Verify Context Injection
        ctx = memory_manager.lifecycle.build_context(current_query="research")
        assert isinstance(ctx, str)
