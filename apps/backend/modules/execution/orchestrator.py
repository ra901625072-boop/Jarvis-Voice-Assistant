"""
orchestrator.py — SwarmOrchestrator enforcing Plan -> Execute -> Verify -> Recover loop.
"""
import asyncio
import logging
import uuid
import time
from typing import Dict, Any, Optional

from ai.contracts import AgentTask, AgentResult, AgentTaskTypes, VerificationReport
from modules.bus.base_bus import AbstractBus
from modules.state import GoalState, DAGNode, NodeStatus
from modules.execution.capability_registry import CapabilityRegistry

logger = logging.getLogger("JARVIS.SwarmOrchestrator")

class SwarmOrchestrator:
    def __init__(self, bus: AbstractBus, capability_registry: CapabilityRegistry):
        self.bus = bus
        self.registry = capability_registry
        self.active_goals: Dict[str, GoalState] = {}

    async def execute_goal(self, user_goal: str, correlation_id: Optional[str] = None) -> AgentResult:
        cid = correlation_id or str(uuid.uuid4())
        goal_state = GoalState(correlation_id=cid, user_goal=user_goal)
        self.active_goals[cid] = goal_state

        logger.info(f"SwarmOrchestrator starting goal execution [{cid}]: '{user_goal}'")

        # ── Step 1: Request Plan from PlannerAgent ───────────────────────────
        plan_task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type=AgentTaskTypes.CREATE_PLAN,
            payload={"goal": user_goal},
            origin_agent="swarm_orchestrator",
            target_agent="planning_agent",
            correlation_id=cid,
        )

        plan_result = await self.bus.dispatch(plan_task, timeout=30.0)
        if not plan_result.success or not isinstance(plan_result.result, list):
            # Fallback single node if planner fails
            initial_nodes = [
                DAGNode(
                    node_id="node_1",
                    task_type="run_grounded_task",
                    description=user_goal,
                    payload={"goal": user_goal},
                    success_criteria={"type": "non_empty_result"}
                )
            ]
        else:
            initial_nodes = []
            for idx, raw_step in enumerate(plan_result.result):
                if isinstance(raw_step, dict):
                    initial_nodes.append(DAGNode(
                        node_id=raw_step.get("step_id", f"node_{idx+1}"),
                        task_type=raw_step.get("task_type", "run_grounded_task"),
                        description=raw_step.get("description", str(raw_step)),
                        payload=raw_step.get("payload", {"task": raw_step.get("description", user_goal)}),
                        parent_ids=raw_step.get("dependencies", []),
                        success_criteria=raw_step.get("success_criteria", {"type": "non_empty_result"})
                    ))

        for node in initial_nodes:
            goal_state.add_node(node)

        # ── Step 2: Topological DAG Execution Loop ────────────────────────────
        max_loop_iterations = 20
        iteration = 0

        while iteration < max_loop_iterations:
            iteration += 1
            ready_nodes = goal_state.get_ready_nodes()

            if not ready_nodes:
                # Check if all nodes are completed or if any failed unrecoverably
                all_done = all(n.status == NodeStatus.COMPLETED for n in goal_state.nodes.values())
                any_failed = any(n.status == NodeStatus.FAILED for n in goal_state.nodes.values())

                if all_done:
                    goal_state.is_completed = True
                    results_summary = {nid: n.result for nid, n in goal_state.nodes.items()}
                    return AgentResult(
                        task_id=cid,
                        success=True,
                        result={"status": "completed", "summary": results_summary, "nodes_executed": len(goal_state.nodes)},
                        confidence=0.95
                    )
                elif any_failed:
                    failed_nodes = [nid for nid, n in goal_state.nodes.items() if n.status == NodeStatus.FAILED]
                    return AgentResult(
                        task_id=cid,
                        success=False,
                        result=None,
                        error=f"Goal execution failed on nodes: {failed_nodes}",
                        error_category="dag_execution_failure"
                    )
                else:
                    await asyncio.sleep(0.2)
                    continue

            # Execute ready nodes concurrently
            tasks = [self._execute_node(goal_state, node) for node in ready_nodes]
            await asyncio.gather(*tasks)

        return AgentResult(
            task_id=cid,
            success=False,
            result=None,
            error=f"Exceeded max orchestrator iterations ({max_loop_iterations})",
            error_category="max_iterations_exceeded"
        )

    async def _execute_node(self, goal_state: GoalState, node: DAGNode):
        node.status = NodeStatus.RUNNING
        node.attempts += 1

        # Select agent via CapabilityRegistry
        target_agent = self.registry.select_agent(node.task_type, default_agent="coordinator_agent")
        node.assigned_agent = target_agent

        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type=node.task_type,
            payload=node.payload,
            origin_agent="swarm_orchestrator",
            target_agent=target_agent,
            correlation_id=goal_state.correlation_id,
            success_criteria=node.success_criteria,
        )

        logger.info(f"Dispatching node [{node.node_id}] to agent '{target_agent}'")
        exec_result = await self.bus.dispatch(task)

        # Update telemetry
        self.registry.update_metrics(
            agent_id=target_agent,
            task_type=node.task_type,
            success=exec_result.success,
            confidence=exec_result.confidence
        )

        if not exec_result.success:
            logger.warning(f"Node [{node.node_id}] execution failed: {exec_result.error}. Triggering Recovery.")
            await self._handle_recovery(goal_state, node, exec_result)
            return

        # ── Verification Step ────────────────────────────────────────────────
        node.status = NodeStatus.VERIFYING
        verify_task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type=AgentTaskTypes.VERIFY_RESULT,
            payload={
                "task_id": task.task_id,
                "node_id": node.node_id,
                "task_type": node.task_type,
                "result": exec_result.result,
                "success_criteria": node.success_criteria,
            },
            origin_agent="swarm_orchestrator",
            target_agent="verification_agent",
            correlation_id=goal_state.correlation_id,
        )

        verify_res = await self.bus.dispatch(verify_task, timeout=15.0)
        verified = verify_res.success and (
            isinstance(verify_res.result, dict) and verify_res.result.get("verified", True)
        )

        if verified:
            logger.info(f"Node [{node.node_id}] verified successfully.")
            goal_state.mark_completed(node.node_id, exec_result.result)
        else:
            logger.warning(f"Node [{node.node_id}] verification failed. Triggering Recovery.")
            await self._handle_recovery(goal_state, node, exec_result)

    async def _handle_recovery(self, goal_state: GoalState, node: DAGNode, failed_result: AgentResult):
        node.status = NodeStatus.RECOVERING

        if node.attempts >= 3:
            logger.error(f"Node [{node.node_id}] exhausted retry attempts ({node.attempts}). Marking failed.")
            goal_state.mark_failed(node.node_id, failed_result.error or "Max retries reached")
            return

        recovery_task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type=AgentTaskTypes.RECOVER_FAILURE,
            payload={
                "goal": goal_state.user_goal,
                "failed_node_id": node.node_id,
                "error_context": failed_result.error,
                "agent_id": node.assigned_agent,
                "task_type": node.task_type,
                "attempts": node.attempts,
            },
            origin_agent="swarm_orchestrator",
            target_agent="recovery_agent",
            correlation_id=goal_state.correlation_id,
        )

        rec_res = await self.bus.dispatch(recovery_task, timeout=20.0)

        if rec_res.success and isinstance(rec_res.result, dict) and rec_res.result.get("action") == "retry":
            logger.info(f"Recovery agent advised retry for node [{node.node_id}]. Resetting to PENDING.")
            node.status = NodeStatus.PENDING
        else:
            goal_state.mark_failed(node.node_id, failed_result.error or "Recovery failed")
