import logging
import json
from typing import List, Dict, Any, Optional

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult
from modules.execution.world_state import WorldStateManager
from modules.execution.recovery_engine import RecoveryEngine
from modules.execution.success_patterns import SuccessLearner

logger = logging.getLogger("JARVIS.CoordinatorAgent")

class CoordinatorAgent(BaseAgent):
    """
    Selects which specialist agent(s) should handle a task.
    Coordinates multi-agent collaboration.
    Replaces cognitive_coordinator.py.
    """
    def __init__(self, bus, available_agents: list, memory_manager=None):
        super().__init__(agent_id="coordinator_agent")
        self.bus = bus
        self.available_agents = available_agents
        self.mm = memory_manager
        
        self.world_state = WorldStateManager()
        self.recovery_engine = RecoveryEngine(self.world_state)
        self.success_learner = SuccessLearner(self.mm) if self.mm else None
        
        if not self.mm or not hasattr(self.mm, 'lifecycle'):
            self._has_cognitive_layer = False
        else:
            self._has_cognitive_layer = True
            
        self.bus.register(self.agent_id, self.handle)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type == "select_agent":
                return await self._handle_select_agent(task, payload)
            elif task_type == "coordinate_flow":
                return await self._handle_coordinate_flow(task, payload)
            elif task_type == "arbitrate":
                return await self._handle_arbitrate(task, payload)
            elif task_type == "generate_context":
                return await self._handle_generate_context(task, payload)
            elif task_type == "analyze_failure":
                return await self._handle_analyze_failure(task, payload)
            elif task_type == "evaluate_plan":
                return await self._handle_evaluate_plan(task, payload)
            else:
                return self._create_result(task, success=False, error=f"CoordinatorAgent does not support task type '{task_type}'")
        except Exception as e:
            logger.exception(f"CoordinatorAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))

    async def _handle_select_agent(self, task: AgentTask, payload: dict) -> AgentResult:
        description = payload.get("description", "")
        prompt = f"""
        Given the following task:
        "{description}"
        
        Available agents: {self.available_agents}
        Select the most appropriate agent to handle this task.
        Return JSON with exactly:
        - 'selected_agent': string (one of the available agents)
        - 'reason': string
        """
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse LLM response: {e}")

    async def _handle_coordinate_flow(self, task: AgentTask, payload: dict) -> AgentResult:
        return self._create_result(task, success=True, result={"status": "coordinated", "payload": payload})

    async def _handle_arbitrate(self, task: AgentTask, payload: dict) -> AgentResult:
        return self._create_result(task, success=True, result={"status": "arbitrated", "payload": payload})

    async def _handle_generate_context(self, task: AgentTask, payload: dict) -> AgentResult:
        goal = payload.get("goal", "")
        if not self._has_cognitive_layer:
            return self._create_result(task, success=True, result={"context": ""})
            
        parts = []
        try:
            pref = self.success_learner.get_preferred_workflow(goal)
            if pref:
                parts.append(pref)
            else:
                workflows = self.mm.search_workflows(goal, limit=2)
                if workflows:
                    wf_str = "--- PAST SUCCESSFUL PLANS FOR SIMILAR GOALS ---\n"
                    for wf in workflows:
                        wf_str += f"[Goal: {wf['goal']}]\n{wf['plan']}\n\n"
                    parts.append(wf_str.strip())
        except Exception as e:
            logger.debug(f"Coordinator workflow search failed: {e}")

        try:
            unreliable = self.mm.lifecycle.tool_memory.get_unreliable_tools()
            if unreliable:
                tool_str = "--- CAUTION: UNRELIABLE TOOLS ---\n"
                for t in unreliable:
                    fail_rate = round((1.0 - t['reliability']) * 100, 1)
                    tool_str += f"- {t['tool_name']}: {fail_rate}% failure rate. Prefer alternatives.\n"
                parts.append(tool_str.strip())
        except Exception as e:
            logger.debug(f"Coordinator tool stats check failed: {e}")

        try:
            lessons = self.mm.lifecycle._get_relevant_lessons(goal)
            if lessons:
                parts.append(f"--- RELEVANT LESSONS LEARNED ---\n{lessons}")
        except Exception as e:
            logger.debug(f"Coordinator lesson search failed: {e}")

        try:
            ws = self.world_state.format_state_for_planner()
            parts.append(ws)
        except Exception as e:
            logger.debug(f"Coordinator world state failed: {e}")

        res_ctx = "--- EXECUTION CONTEXT ---\n" + "\n\n".join(parts) if parts else "No historical planning context available for this goal."
        return self._create_result(task, success=True, result={"context": res_ctx})

    async def _handle_analyze_failure(self, task: AgentTask, payload: dict) -> AgentResult:
        goal = payload.get("goal", "")
        failed_task = payload.get("failed_task", "")
        error_reason = payload.get("error_reason", "")
        
        analysis_parts = [
            f"⚠️ EXECUTION FAILURE ⚠️",
            f"Goal: {goal}",
            f"Failed Task: {failed_task}",
            f"Error Reason: {error_reason}",
            ""
        ]

        if not self._has_cognitive_layer:
            analysis_parts.append("Recommendation: Analyze the error and attempt to formulate a new plan.")
            return self._create_result(task, success=True, result={"analysis": "\n".join(analysis_parts)})

        query = f"{failed_task} {error_reason}"
        lessons = self.mm.lifecycle._get_relevant_lessons(query)
        
        if lessons:
            analysis_parts.append("--- RELEVANT HISTORICAL LESSONS ---")
            analysis_parts.append(lessons)
            analysis_parts.append("")
            analysis_parts.append(
                "DIRECTIVE: Replan the workflow immediately using the historical lessons above. "
                "Avoid the approach that just failed and prefer alternative tools or strategies."
            )
        else:
            try:
                stats = self.mm.get_workflow_stats(failed_task)
                if stats and stats['fail_count'] > stats['success_count']:
                    analysis_parts.append(
                        f"WARNING: This task pattern has a high historical failure rate "
                        f"({stats['fail_count']} failures vs {stats['success_count']} successes)."
                    )
            except Exception:
                pass
                
            analysis_parts.append(
                "DIRECTIVE: The primary approach failed. Analyze the error above. "
                "Identify an alternative tool or strategy and call create_plan to try again. "
                "Do not repeat the exact same steps."
            )

        return self._create_result(task, success=True, result={"analysis": "\n".join(analysis_parts)})

    async def _handle_evaluate_plan(self, task: AgentTask, payload: dict) -> AgentResult:
        goal = payload.get("goal", "")
        subtasks = payload.get("subtasks", [])
        
        if not self._has_cognitive_layer:
            return self._create_result(task, success=True, result={"evaluation": "Plan accepted."})
            
        warnings = []
        try:
            unreliable = self.mm.lifecycle.tool_memory.get_unreliable_tools()
            unreliable_names = {t['tool_name'].lower() for t in unreliable}
            
            for subtask in subtasks:
                task_lower = subtask.lower()
                for bad_tool in unreliable_names:
                    if bad_tool in task_lower:
                        warnings.append(
                            f"Risk: Task '{subtask}' appears to use '{bad_tool}', "
                            f"which has a high historical failure rate."
                        )
        except Exception:
            pass

        try:
            stats = self.mm.get_workflow_stats(goal)
            if stats and stats['fail_count'] > 3 and stats['success_rate'] < 30.0:
                last_err = stats.get('last_error', 'unknown')
                warnings.append(
                    f"Risk: The goal pattern '{goal[:40]}...' historically fails {100-stats['success_rate']}% of the time. "
                    f"Last error: {last_err}"
                )
        except Exception:
            pass

        eval_res = "PLAN WARNINGS:\n" + "\n".join(warnings) + "\nProceed with caution." if warnings else "Plan accepted. No known historical risks detected."
        return self._create_result(task, success=True, result={"evaluation": eval_res})
