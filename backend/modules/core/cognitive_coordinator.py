"""
cognitive_coordinator.py
------------------------
The JARVIS Cognitive Coordination Layer (Phase 6 & 7).

Purpose
-------
Acts as the central brain coordinating Memory, Planning, Execution, and Reflection.
Closes the loop between the planner and memory systems to achieve true autonomy.

Responsibilities
----------------
1. generate_execution_context: Injects past workflows, tool stats, and lessons
   into the planner *before* it generates a plan.
2. analyze_failure_and_replan: On failure, searches for lessons and alternative
   strategies, returning an actionable prompt to guide dynamic replanning.
3. evaluate_plan: Reviews a proposed plan against known tool reliability issues
   before execution begins.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from modules.execution.world_state import WorldStateManager
from modules.execution.recovery_engine import RecoveryEngine
from modules.execution.success_patterns import SuccessLearner

logger = logging.getLogger("JARVIS.CognitiveCoordinator")


class CognitiveCoordinator:
    """
    Coordinates interactions between Memory Manager and Task Planner,
    enabling dynamic replanning and context-aware execution.
    """

    def __init__(self, memory_manager):
        self.mm = memory_manager
        self.world_state = WorldStateManager()
        self.recovery_engine = RecoveryEngine(self.world_state)
        self.success_learner = SuccessLearner(self.mm)
        
        # Access cognitive memory subsystems through the lifecycle orchestrator
        if not hasattr(self.mm, 'lifecycle'):
            logger.warning("CognitiveCoordinator initialized without Phase 5 Lifecycle.")
            self._has_cognitive_layer = False
        else:
            self._has_cognitive_layer = True

    # ------------------------------------------------------------------ #
    # 1. Planner Execution Context                                         #
    # ------------------------------------------------------------------ #

    def generate_execution_context(self, goal: str) -> str:
        """
        Gather context specifically tailored for planning a workflow for `goal`.
        Returns a formatted string to inject into the planner's LLM prompt.
        """
        if not self._has_cognitive_layer:
            return ""

        parts = []

        # 1. Past Workflow History & Preferred Workflows
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

        # 2. Known Unreliable Tools (Tool Intelligence)
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

        # 3. Relevant Lessons Learned (Experience Replay)
        try:
            # Query lessons related to the goal keywords
            lessons = self.mm.lifecycle._get_relevant_lessons(goal)
            if lessons:
                parts.append(f"--- RELEVANT LESSONS LEARNED ---\n{lessons}")
        except Exception as e:
            logger.debug(f"Coordinator lesson search failed: {e}")

        # 4. Current World State
        try:
            ws = self.world_state.format_state_for_planner()
            parts.append(ws)
        except Exception as e:
            logger.debug(f"Coordinator world state failed: {e}")

        if not parts:
            return "No historical planning context available for this goal."

        return "--- EXECUTION CONTEXT ---\n" + "\n\n".join(parts)

    # ------------------------------------------------------------------ #
    # 2. Dynamic Replanning & Failure Analysis                             #
    # ------------------------------------------------------------------ #

    def analyze_failure_and_replan(self, goal: str, failed_task: str, error_reason: str) -> str:
        """
        Triggered when a task fails during execution.
        Searches memory for similar past failures and relevant lessons to generate
        a concrete replanning directive for the LLM.
        """
        logger.info(f"CognitiveCoordinator: Analyzing failure for '{failed_task}'...")
        
        analysis_parts = [
            f"⚠️ EXECUTION FAILURE ⚠️",
            f"Goal: {goal}",
            f"Failed Task: {failed_task}",
            f"Error Reason: {error_reason}",
            ""
        ]

        if not self._has_cognitive_layer:
            analysis_parts.append("Recommendation: Analyze the error and attempt to formulate a new plan.")
            return "\n".join(analysis_parts)

        # Look for lessons learned matching the error keywords or the task
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
            # Check if this specific tool/task pattern fails often
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

        return "\n".join(analysis_parts)

    # ------------------------------------------------------------------ #
    # 3. Plan Evaluation                                                   #
    # ------------------------------------------------------------------ #

    def evaluate_plan(self, goal: str, subtasks: List[str]) -> str:
        """
        Checks a newly generated plan for known risks before it begins execution.
        """
        if not self._has_cognitive_layer:
            return "Plan accepted."
            
        warnings = []
        
        # 1. Check for unreliable tools inferred from task descriptions
        try:
            unreliable = self.mm.lifecycle.tool_memory.get_unreliable_tools()
            unreliable_names = {t['tool_name'].lower() for t in unreliable}
            
            for task in subtasks:
                task_lower = task.lower()
                for bad_tool in unreliable_names:
                    if bad_tool in task_lower:
                        warnings.append(
                            f"Risk: Task '{task}' appears to use '{bad_tool}', "
                            f"which has a high historical failure rate."
                        )
        except Exception:
            pass

        # 2. Check if this exact plan matches a highly failed workflow
        try:
            stats = self.mm.get_workflow_stats(goal)
            if stats and stats['fail_count'] > 3 and stats['success_rate'] < 30.0:
                warnings.append(
                    f"Risk: The goal pattern '{goal[:40]}...' historically fails {100-stats['success_rate']}% of the time. "
                    f"Last error: {stats['last_error']}"
                )
        except Exception:
            pass

        if warnings:
            return "PLAN WARNINGS:\n" + "\n".join(warnings) + "\nProceed with caution."
            
        return "Plan accepted. No known historical risks detected."
