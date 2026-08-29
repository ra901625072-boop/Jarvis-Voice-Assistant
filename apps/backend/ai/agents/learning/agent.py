import logging
import json
import uuid
import os
from datetime import datetime
from typing import Dict, Any, Optional

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult
from ai.agents.learning.prompts import (
    SYSTEM_PROMPT,
    ANALYZE_OUTCOME_PROMPT,
    REVIEW_FAILURE_PROMPT,
    REVIEW_SUCCESS_PROMPT,
    PROPOSE_PROMPT_PATCH_PROMPT,
    SUMMARIZE_LEARNING_CYCLE_PROMPT
)
from ai.agents.learning.schemas import (
    OutcomeAnalysisSchema,
    FailureReviewSchema,
    SuccessReviewSchema,
    PromptPatchSchema,
    LearningCycleSummarySchema
)
from ai.agents.learning.policy import LearningPolicy
from ai.agents.learning.curriculum import generate_curriculum_for_weakness
from ai.agents.learning.evaluator import LearningEvaluator
from modules.learning.dashboard_renderer import DashboardRenderer

logger = logging.getLogger("JARVIS.LearningAgent")

class LearningAgent(BaseAgent):
    """
    Decides what knowledge matters and how it should change the system.
    """
    def __init__(self, bus, memory=None):
        super().__init__(agent_id="learning_agent")
        self.bus = bus
        self.mm = memory

        # Instantiate support managers if memory is available
        from modules.learning.learning_orchestrator import LearningOrchestrator
        from modules.learning.curriculum_manager import CurriculumManager
        from modules.learning.prompt_patch_manager import PromptPatchManager
        from modules.learning.benchmark_manager import BenchmarkManager
        from modules.learning.evaluator_engine import EvaluatorEngine
        from modules.learning.root_cause_analyzer import RootCauseAnalyzer
        from modules.learning.memory_consolidator import MemoryConsolidator
        from modules.learning.skill_synthesizer import SkillSynthesizer

        self.evaluator = EvaluatorEngine()
        self.root_cause_analyzer = RootCauseAnalyzer()

        if self.mm:
            self.orchestrator = LearningOrchestrator(self.mm)
            self.curriculum_mgr = CurriculumManager(self.mm)
            self.prompt_patch_mgr = PromptPatchManager(self.orchestrator)
            self.benchmark_mgr = BenchmarkManager(self.orchestrator)
            self.consolidator = MemoryConsolidator(self.mm)
            self.skill_synthesizer = SkillSynthesizer(self.mm)
        else:
            self.orchestrator = None
            self.curriculum_mgr = None
            self.prompt_patch_mgr = None
            self.benchmark_mgr = None
            self.consolidator = None
            self.skill_synthesizer = None

        self.bus.register(self.agent_id, self.handle)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload or {}

        try:
            if task_type == "health_check":
                return self._create_result(task, success=True, result={"status": "ok"})
            elif task_type == "analyze_outcome":
                return await self._handle_analyze_outcome(task, payload)
            elif task_type == "evaluate_episode":
                return await self._handle_evaluate_episode(task, payload)
            elif task_type == "consolidate_memories":
                return await self._handle_consolidate_memories(task, payload)
            elif task_type == "synthesize_skill":
                return await self._handle_synthesize_skill(task, payload)
            elif task_type == "promote_memory":
                return await self._handle_promote_memory(task, payload)
            elif task_type == "get_active_strategies":
                return await self._handle_get_active_strategies(task, payload)
            elif task_type == "review_failure_pattern":
                return await self._handle_review_failure_pattern(task, payload)
            elif task_type == "review_success_pattern":
                return await self._handle_review_success_pattern(task, payload)
            elif task_type == "evaluate_agent_capability":
                return await self._handle_evaluate_agent_capability(task, payload)
            elif task_type == "generate_curriculum":
                return await self._handle_generate_curriculum(task, payload)
            elif task_type == "propose_prompt_patch":
                return await self._handle_propose_prompt_patch(task, payload)
            elif task_type == "propose_routing_change":
                return await self._handle_propose_routing_change(task, payload)
            elif task_type == "build_regression_case":
                return await self._handle_build_regression_case(task, payload)
            elif task_type == "summarize_learning_cycle":
                return await self._handle_summarize_learning_cycle(task, payload)
            elif task_type == "audit_learning_health":
                return await self._handle_audit_learning_health(task, payload)
            elif task_type == "render_learning_dashboard":
                return await self._handle_render_learning_dashboard(task, payload)
            else:
                return self._create_result(task, success=False, error=f"LearningAgent does not support task type '{task_type}'")
        except Exception as e:
            logger.exception(f"LearningAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))

    async def _handle_analyze_outcome(self, task: AgentTask, payload: dict) -> AgentResult:
        agent_id = payload.get("agent_id")
        task_type = payload.get("task_type")
        task_id = payload.get("task_id")
        success = payload.get("success", False)
        error_summary = payload.get("error_summary", "")
        goal_hint = payload.get("goal_hint", "")
        duration_ms = payload.get("duration_ms", 0.0)

        if not agent_id or not task_type:
            return self._create_result(task, success=False, error="Missing agent_id or task_type in payload")

        if not LearningPolicy.should_process_outcome(goal_hint):
            return self._create_result(task, success=True, result={"status": "ignored", "reason": "synthetic_test"})

        prompt = ANALYZE_OUTCOME_PROMPT.format(
            agent_id=agent_id,
            task_type=task_type,
            success=success,
            duration_ms=duration_ms,
            error_summary=error_summary,
            goal_hint=goal_hint
        )

        response = await self.generate_response(prompt, system_instruction=SYSTEM_PROMPT, response_mime_type="application/json")
        data = self._parse_json_response(response)

        # Fallback handling on schema validation failure
        if not OutcomeAnalysisSchema.validate(data):
            logger.warning("LearningAgent: OutcomeAnalysis validation failed. Applying conservative fallback defaults.")
            data = {
                "classification": "one_time_failure" if not success else "noise",
                "severity": "warning" if not success else "info",
                "pattern_key": "unparsed_fallback",
                "summary": f"Fallback parse recovery for task outcome error: {error_summary}" if not success else "Unparsed outcome data logged"
            }

        # Record event in DB
        if self.orchestrator:
            self.orchestrator.log_event(
                agent_id=agent_id,
                task_type=task_type,
                event_type=data.get("classification"),
                severity=data.get("severity", "info"),
                pattern_key=data.get("pattern_key"),
                summary=data.get("summary", "")
            )

        return self._create_result(task, success=True, result=data)

    async def _handle_review_failure_pattern(self, task: AgentTask, payload: dict) -> AgentResult:
        agent_id = payload.get("agent_id")
        task_type = payload.get("task_type")
        streak = payload.get("streak", 1)
        pattern = payload.get("pattern", "")
        goals = payload.get("goals", "")

        if not agent_id or not task_type:
            return self._create_result(task, success=False, error="Missing agent_id or task_type in payload")

        prompt = REVIEW_FAILURE_PROMPT.format(
            agent_id=agent_id,
            task_type=task_type,
            streak=streak,
            pattern=pattern,
            goals=goals
        )

        response = await self.generate_response(prompt, system_instruction=SYSTEM_PROMPT, response_mime_type="application/json")
        data = self._parse_json_response(response)

        if not FailureReviewSchema.validate(data):
            logger.warning("LearningAgent: FailureReview validation failed. Using fallback lesson.")
            data = {
                "lesson": f"Failure streak observed in {task_type}. Streak occurrences count: {streak}.",
                "importance": 1
            }

        # Store lesson in DB if database is connected
        if self.mm and hasattr(self.mm, 'lifecycle') and hasattr(self.mm.lifecycle, 'replayer'):
            source_pattern = f"la_{agent_id}_{task_type}_{pattern}"[:64]
            self.mm.lifecycle.replayer._store_lesson(
                lesson=data.get("lesson"),
                source_pattern=source_pattern,
                occurrence_count=streak,
                project="general"
            )

        return self._create_result(task, success=True, result=data)

    async def _handle_review_success_pattern(self, task: AgentTask, payload: dict) -> AgentResult:
        agent_id = payload.get("agent_id")
        task_type = payload.get("task_type")
        goal = payload.get("goal", "")
        duration_ms = payload.get("duration_ms", 0.0)

        if not agent_id or not task_type or not goal:
            return self._create_result(task, success=False, error="Missing agent_id, task_type or goal in payload")

        prompt = REVIEW_SUCCESS_PROMPT.format(
            agent_id=agent_id,
            task_type=task_type,
            goal=goal,
            duration_ms=duration_ms
        )

        response = await self.generate_response(prompt, system_instruction=SYSTEM_PROMPT, response_mime_type="application/json")
        data = self._parse_json_response(response)

        if not SuccessReviewSchema.validate(data):
            logger.warning("LearningAgent: SuccessReview validation failed. Using fallback success review.")
            data = {
                "goal": goal,
                "plan_json": [{"action": "execute_task", "agent_id": agent_id, "task_type": task_type}],
                "score": 0.8
            }

        # Store success pattern in DB
        if self.mm:
            ts = datetime.now().isoformat()
            plan_json_str = json.dumps(data.get("plan_json", []))
            with self.mm._lock:
                self.mm.dbs["conversations"].execute(
                    """INSERT INTO success_patterns (goal, plan_json, score, created_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(goal) DO UPDATE SET score=excluded.score, plan_json=excluded.plan_json""",
                    (data.get("goal"), plan_json_str, data.get("score", 1.0), ts)
                )
                self.mm.dbs["conversations"].commit()

        return self._create_result(task, success=True, result=data)

    async def _handle_evaluate_agent_capability(self, task: AgentTask, payload: dict) -> AgentResult:
        agent_id = payload.get("agent_id")
        task_type = payload.get("task_type")

        if not agent_id or not task_type:
            return self._create_result(task, success=False, error="Missing agent_id or task_type in payload")

        stats = {}
        if self.mm:
            with self.mm._lock:
                row = self.mm.dbs["conversations"].execute(
                    """SELECT ema_score, success_rate, total_runs, confidence FROM agent_capability_scores
                       WHERE agent_id = ? AND task_type = ?""",
                    (agent_id, task_type)
                ).fetchone()
                if row:
                    stats = {
                        "ema_score": row[0],
                        "success_rate": row[1],
                        "total_runs": row[2],
                        "confidence": row[3],
                        "level": LearningPolicy.evaluate_ema_threshold(row[0] or 0.8)
                    }
                else:
                    stats = {
                        "ema_score": 0.8,
                        "success_rate": 1.0,
                        "total_runs": 0,
                        "confidence": 0.8,
                        "level": "normal"
                    }

        return self._create_result(task, success=True, result=stats)

    async def _handle_generate_curriculum(self, task: AgentTask, payload: dict) -> AgentResult:
        agent_id = payload.get("agent_id")
        task_type = payload.get("task_type")
        failure_pattern = payload.get("failure_pattern", "")

        if not agent_id or not task_type:
            return self._create_result(task, success=False, error="Missing agent_id or task_type in payload")

        curr = generate_curriculum_for_weakness(agent_id, task_type, failure_pattern)

        if self.curriculum_mgr:
            self.curriculum_mgr.add_curriculum_item(
                agent_id=agent_id,
                curriculum_type=curr.get("curriculum_type", "general"),
                prompt=curr.get("prompt", ""),
                expected_behavior=curr.get("expected_behavior"),
                evaluation_rule=curr.get("evaluation_rule")
            )

        return self._create_result(task, success=True, result=curr)

    async def _handle_propose_prompt_patch(self, task: AgentTask, payload: dict) -> AgentResult:
        agent_id = payload.get("agent_id")
        issue = payload.get("issue")
        original_prompt_snippet = payload.get("original_prompt_snippet", "")

        if not agent_id or not issue:
            return self._create_result(task, success=False, error="Missing agent_id or issue in payload")

        prompt = PROPOSE_PROMPT_PATCH_PROMPT.format(
            agent_id=agent_id,
            issue=issue,
            original_prompt_snippet=original_prompt_snippet
        )

        response = await self.generate_response(prompt, system_instruction=SYSTEM_PROMPT, response_mime_type="application/json")
        data = self._parse_json_response(response)

        # Fallback handling on prompt patch validation failure
        if not PromptPatchSchema.validate(data):
            logger.warning("LearningAgent: PromptPatch validation failed. Using fallback review details.")
            data = {
                "agent_id": agent_id,
                "recommended_patch": f"# Fallback review recommendation for prompt improvement in: {issue}",
                "reason": "Fallback recovery triggered due to invalid JSON schema response from LLM."
            }

        # Apply confidence check policy
        risk_level = LearningPolicy.evaluate_recommendation_risk(data)
        if risk_level == "review" and self.orchestrator:
            # We flag this in the reason for review
            data["reason"] = f"[REVIEW REQUIRED - Low Confidence or Warning] {data.get('reason', '')}"

        if self.prompt_patch_mgr:
            self.prompt_patch_mgr.propose_patch(
                agent_id=agent_id,
                issue=issue,
                original_prompt_snippet=original_prompt_snippet,
                recommended_patch=data.get("recommended_patch", ""),
                reason=data.get("reason", "")
            )

        return self._create_result(task, success=True, result=data)

    async def _handle_propose_routing_change(self, task: AgentTask, payload: dict) -> AgentResult:
        agent_id = payload.get("agent_id")
        routing_action = payload.get("routing_action")

        if not agent_id or not routing_action:
            return self._create_result(task, success=False, error="Missing agent_id or routing_action in payload")

        # Evaluate risk level
        risk_level = LearningPolicy.evaluate_recommendation_risk(payload)
        status = "pending" if risk_level == "auto_apply" else "pending_review"

        if self.orchestrator:
            rec_id = self.orchestrator.create_recommendation(
                source_event_id=None,
                target_agent="supervisor_agent",
                recommendation_type="routing_change",
                payload={"agent_id": agent_id, "routing_action": routing_action, "status": status}
            )
            return self._create_result(task, success=True, result={"recommendation_id": rec_id, "status": "proposed"})

        return self._create_result(task, success=True, result={"status": "ignored", "reason": "no_orchestrator"})

    async def _handle_build_regression_case(self, task: AgentTask, payload: dict) -> AgentResult:
        agent_id = payload.get("agent_id")
        task_type = payload.get("task_type")
        goal = payload.get("goal")
        failure_pattern = payload.get("failure_pattern", "")
        error_summary = payload.get("error_summary", "")

        if not agent_id or not task_type or not goal:
            return self._create_result(task, success=False, error="Missing agent_id, task_type or goal in payload")

        if self.benchmark_mgr:
            rec_id = self.benchmark_mgr.propose_regression_case(
                agent_id=agent_id,
                task_type=task_type,
                goal=goal,
                failure_pattern=failure_pattern,
                error_summary=error_summary
            )
            return self._create_result(task, success=True, result={"recommendation_id": rec_id, "status": "proposed"})

        return self._create_result(task, success=True, result={"status": "ignored", "reason": "no_benchmark_mgr"})

    async def _handle_summarize_learning_cycle(self, task: AgentTask, payload: dict) -> AgentResult:
        events = []
        capabilities = []
        gaps = []

        if self.orchestrator:
            events = self.orchestrator.get_pending_recommendations()[:10]
            capabilities = self.mm.dbs["conversations"].execute(
                "SELECT agent_id, task_type, ema_score FROM agent_capability_scores ORDER BY ema_score ASC LIMIT 10"
            ).fetchall()
            gaps = self.orchestrator.get_skill_gaps()[:10]

        prompt = SUMMARIZE_LEARNING_CYCLE_PROMPT.format(
            events=str(events),
            capabilities=str(capabilities),
            gaps=str(gaps)
        )

        response = await self.generate_response(prompt, system_instruction=SYSTEM_PROMPT, response_mime_type="application/json")
        data = self._parse_json_response(response)

        if not LearningCycleSummarySchema.validate(data):
            logger.warning("LearningAgent: LearningCycleSummary validation failed. Using fallback summary.")
            data = {
                "summary": "Completed self-learning nightly cycle run. Active skill gaps monitored.",
                "insights": [{"insight": "Continuous pattern monitoring active.", "severity": "info"}],
                "actions": [{"action": "audit_learning_health"}]
            }

        return self._create_result(task, success=True, result=data)

    async def _handle_audit_learning_health(self, task: AgentTask, payload: dict) -> AgentResult:
        stats = {}
        if self.mm:
            with self.mm._lock:
                stats = {
                    "learning_events": self.mm.dbs["conversations"].execute("SELECT COUNT(*) FROM learning_events").fetchone()[0],
                    "learning_recommendations": self.mm.dbs["conversations"].execute("SELECT COUNT(*) FROM learning_recommendations").fetchone()[0],
                    "agent_skill_gaps": self.mm.dbs["conversations"].execute("SELECT COUNT(*) FROM agent_skill_gaps").fetchone()[0],
                    "curriculum_items": self.mm.dbs["conversations"].execute("SELECT COUNT(*) FROM curriculum_items").fetchone()[0],
                    "lessons_learned": self.mm.dbs["conversations"].execute("SELECT COUNT(*) FROM lessons_learned").fetchone()[0],
                    "audit_trail_count": self.mm.dbs["conversations"].execute("SELECT COUNT(*) FROM learning_audit_log").fetchone()[0]
                }
                
                # Prune old logs using orchestrator if available
                if self.orchestrator:
                    pruned = self.orchestrator.prune_stale_records(days=30)
                    stats.update(pruned)

        return self._create_result(task, success=True, result=stats)

    async def _handle_render_learning_dashboard(self, task: AgentTask, payload: dict) -> AgentResult:
        if not self.mm:
            return self._create_result(task, success=False, error="MemoryManager is not connected.")

        output_path = payload.get("output_path")
        
        cli_report = DashboardRenderer.render_cli_report(self.mm)
        html_dashboard_path = DashboardRenderer.generate_static_html(self.mm, output_path=output_path)

        result_data = {
            "cli_report": cli_report,
            "html_dashboard_path": html_dashboard_path
        }
        return self._create_result(task, success=True, result=result_data)

    async def _handle_evaluate_episode(self, task: AgentTask, payload: dict) -> AgentResult:
        from modules.learning.trajectory_collector import TrajectoryCollector
        episode_id = payload.get("episode_id")
        episode = payload.get("episode")

        if not episode and episode_id and self.mm:
            episode = TrajectoryCollector.get_episode(self.mm, episode_id)

        if not episode:
            return self._create_result(task, success=False, error="Missing episode or episode_id in payload")

        eval_result = self.evaluator.evaluate_episode(episode)
        root_cause = {}
        if not episode.get("success", False):
            root_cause = self.root_cause_analyzer.analyze(episode)
            eval_result["root_cause"] = root_cause

        # Update episode in DB with evaluation
        if episode_id and self.mm:
            try:
                with self.mm._lock:
                    self.mm.dbs["conversations"].execute(
                        "UPDATE episodes SET evaluation_json = ? WHERE episode_id = ?",
                        (json.dumps(eval_result), episode_id)
                    )
                    self.mm.dbs["conversations"].commit()
            except Exception as e:
                logger.error(f"LearningAgent: failed to save evaluation to episode {episode_id}: {e}")

        return self._create_result(task, success=True, result=eval_result)

    async def _handle_consolidate_memories(self, task: AgentTask, payload: dict) -> AgentResult:
        if not self.consolidator:
            return self._create_result(task, success=False, error="MemoryManager is not connected.")

        min_cluster_size = payload.get("min_cluster_size", 2)
        summary = self.consolidator.consolidate_episodes(min_cluster_size=min_cluster_size)
        return self._create_result(task, success=True, result=summary)

    async def _handle_synthesize_skill(self, task: AgentTask, payload: dict) -> AgentResult:
        if not self.skill_synthesizer:
            return self._create_result(task, success=False, error="SkillSynthesizer is not initialized.")

        strategy_id = payload.get("strategy_id")
        if not strategy_id:
            return self._create_result(task, success=False, error="Missing strategy_id in payload")

        candidate_id = self.skill_synthesizer.create_skill_candidate(strategy_id)
        if not candidate_id:
            return self._create_result(task, success=False, error="Failed to create safe skill candidate from strategy.")

        auto_distill = payload.get("auto_distill", False)
        distilled = False
        if auto_distill:
            distilled = self.skill_synthesizer.test_and_distill_skill(candidate_id)

        return self._create_result(task, success=True, result={"candidate_id": candidate_id, "distilled": distilled})

    async def _handle_promote_memory(self, task: AgentTask, payload: dict) -> AgentResult:
        if not self.consolidator:
            return self._create_result(task, success=False, error="MemoryConsolidator is not initialized.")

        strategy_id = payload.get("strategy_id")
        target_status = payload.get("target_status")
        reason = payload.get("reason", "Manual or automated promotion")

        if not strategy_id or not target_status:
            return self._create_result(task, success=False, error="Missing strategy_id or target_status in payload")

        success = self.consolidator.promote_strategy(strategy_id, target_status, reason)
        return self._create_result(task, success=success, result={"strategy_id": strategy_id, "status": target_status})

    async def _handle_get_active_strategies(self, task: AgentTask, payload: dict) -> AgentResult:
        if not self.consolidator:
            return self._create_result(task, success=False, error="MemoryConsolidator is not initialized.")

        category = payload.get("category")
        min_status = payload.get("min_status", "validated")
        strategies = self.consolidator.get_active_strategies(category=category, min_status=min_status)
        return self._create_result(task, success=True, result={"strategies": strategies})
