import logging

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.RecoveryAgent")

class RecoveryAgent(BaseAgent):
    """
    Handles failures autonomously.
    Decides whether to retry, replan, or escalate to user.
    """
    def __init__(self, bus, memory=None):
        super().__init__(agent_id="recovery_agent")
        self.bus = bus
        self.memory = memory
        self.bus.register(self.agent_id, self.handle)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type == "recover_failure":
                return await self._handle_recover_failure(task, payload)
            else:
                return self._create_result(task, success=False, error=f"RecoveryAgent does not support task type '{task_type}'")
        except Exception as e:
            logger.exception(f"RecoveryAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))

    async def _handle_recover_failure(self, task: AgentTask, payload: dict) -> AgentResult:
        failed_task_desc = payload.get("failed_task_description", "")
        error_context = payload.get("error_context", "")
        goal = payload.get("goal", "")
        agent_id = payload.get("agent_id", "execution_agent")
        task_type_param = payload.get("task_type", "unknown")
        
        from modules.learning import failure_patterns
        pattern_key = failure_patterns.extract_pattern(error_context)

        # Retrieve relevant lessons from DB with prioritized matching
        lessons = []
        if self.memory:
            try:
                with self.memory._lock:
                    # 1. Exact match on pattern_key
                    rows = self.memory.dbs["conversations"].execute(
                        """SELECT lesson FROM lessons_learned 
                           WHERE pattern_key = ?
                           ORDER BY occurrence_count DESC LIMIT 3""",
                        (pattern_key,)
                    ).fetchall()
                    for r in rows:
                        lessons.append(f"- {r[0]}")
                    
                    # 2. Fuzzy match on pattern_key
                    if len(lessons) < 3:
                        placeholders = ",".join(["?"] * len(lessons)) if lessons else "''"
                        rows = self.memory.dbs["conversations"].execute(
                            f"""SELECT lesson FROM lessons_learned 
                               WHERE pattern_key LIKE ? AND lesson NOT IN ({placeholders})
                               ORDER BY occurrence_count DESC LIMIT {3 - len(lessons)}""",
                            (f"%{pattern_key}%", *[l[2:] for l in lessons]) if lessons else (f"%{pattern_key}%",)
                        ).fetchall()
                        for r in rows:
                            lessons.append(f"- {r[0]}")

                    # 3. Fallback to LIKE on source_pattern / lesson
                    if len(lessons) < 3:
                        placeholders = ",".join(["?"] * len(lessons)) if lessons else "''"
                        rows = self.memory.dbs["conversations"].execute(
                            f"""SELECT lesson FROM lessons_learned 
                               WHERE (source_pattern LIKE ? OR source_pattern LIKE ? OR lesson LIKE ?) 
                                 AND lesson NOT IN ({placeholders})
                               ORDER BY occurrence_count DESC LIMIT {3 - len(lessons)}""",
                            (f"%{pattern_key}%", f"%{failed_task_desc}%", f"%{pattern_key}%", *[l[2:] for l in lessons]) if lessons else (f"%{pattern_key}%", f"%{failed_task_desc}%", f"%{pattern_key}%")
                        ).fetchall()
                        for r in rows:
                            lessons.append(f"- {r[0]}")
            except Exception as e:
                logger.warning(f"Failed to query lessons_learned for recovery grounding: {e}")

        lessons_context = "\n".join(lessons) if lessons else "None available."

        # Query failure streak for the specific agent / task
        current_streak = 0
        if self.memory:
            try:
                with self.memory._lock:
                    row = self.memory.dbs["conversations"].execute(
                        "SELECT streak FROM agent_failure_streaks WHERE agent_id = ? AND task_type = ?",
                        (agent_id, task_type_param)
                    ).fetchone()
                    if row:
                        current_streak = row[0]
            except Exception as e:
                logger.warning(f"Failed to query current failure streak: {e}")

        # Retrieve all failure streaks for grounding context
        streaks = []
        if self.memory:
            try:
                with self.memory._lock:
                    rows = self.memory.dbs["conversations"].execute(
                        "SELECT agent_id, task_type, streak, last_pattern FROM agent_failure_streaks WHERE streak >= 2"
                    ).fetchall()
                    for r in rows:
                        streaks.append(f"- Agent '{r[0]}' on task '{r[1]}' has failed {r[2]} times consecutively (last pattern: {r[3]})")
            except Exception as e:
                logger.warning(f"Failed to query agent_failure_streaks for recovery grounding: {e}")

        streaks_context = "\n".join(streaks) if streaks else "None active."

        prompt = f"""
        You are JARVIS's Recovery Engine.
        A task has failed in the execution DAG. Analyze the failure and provide a recovery directive.
        
        Goal: {goal}
        Task: {failed_task_desc}
        Error: {error_context}
        
        Error Pattern: {pattern_key}
        
        Relevant Lessons Learned:
        {lessons_context}
        
        Active Failure Streaks:
        {streaks_context}
        
        Return JSON with exactly:
        - 'action': string (one of: 'retry', 'replan', 'debug', 'escalate')
        - 'reason': string explaining why this action was chosen
        - 'corrected_plan': string (if replan) or null

        Guidelines:
        1. If there is an active failure streak for a target agent/task, bias towards 'replan' or 'escalate' instead of 'retry' to avoid infinite loops.
        2. Utilize the lessons learned to avoid repeating past mistakes.
        """
        
        logger.info(f"RecoveryAgent triggered for failed task: '{failed_task_desc}'. Error context: {error_context[:200]}")
        logger.info(f"RecoveryAgent Grounding Context: pattern_key={pattern_key}, lessons_found={len(lessons)}, current_streak={current_streak}")
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            action = data.get("action", "escalate")
            reason = data.get("reason", "")
            
            # Global recovery attempts counter logic
            from modules.task.state_manager import AgentStateManager
            state_mgr = AgentStateManager()
            state_mgr.recovery_attempts += 1
            
            MAX_RECOVERY_ATTEMPTS = 3
            if state_mgr.recovery_attempts > MAX_RECOVERY_ATTEMPTS:
                logger.warning(f"Global recovery attempts limit exceeded ({state_mgr.recovery_attempts} > {MAX_RECOVERY_ATTEMPTS}). Forcing 'escalate'.")
                action = "escalate"
                data["action"] = "escalate"
                data["reason"] = f"Override to escalate because maximum global recovery attempts ({MAX_RECOVERY_ATTEMPTS}) for the goal have been exceeded."

            # Failure streak cap logic
            if action == "retry" and current_streak >= 2:
                logger.warning(f"Hard-cap exceeded for retry (current streak: {current_streak}). Overriding 'retry' to 'replan'.")
                action = "replan"
                data["action"] = "replan"
                data["reason"] = f"Override to replan because the task has failed {current_streak} times consecutively."

            logger.info(f"RecoveryAgent decided action: '{action}'. Reason: '{reason}'")
            
            # Emit observability trace span event
            try:
                from modules.observability.trace import TraceSpan, SpanEvent
                from container import ServiceContainer
                import threading
                
                span = TraceSpan(
                    trace_id=task.task_id,
                    agent_id=self.agent_id,
                    task_type="recover_failure"
                )
                span.events.append(SpanEvent(
                    name="recovery_decision",
                    data={
                        "decision": action,
                        "reason": data.get("reason", reason),
                        "grounding": {
                            "pattern_key": pattern_key,
                            "lessons_count": len(lessons),
                            "streak_count": current_streak,
                            "global_recovery_attempts": state_mgr.recovery_attempts
                        }
                    }
                ))
                span.finish(success=True)
                trace_store = ServiceContainer.instance().get_or_none("trace_store")
                if trace_store:
                    trace_store.enqueue_save(span)
            except Exception as obs_err:
                logger.warning(f"Failed to record recovery observability event: {obs_err}")

            if action == "retry":
                data["dispatched"] = "none"
                # Just return to let ExecutionAgent handle the retry loop
            
            elif action == "debug":
                import uuid
                debug_task = AgentTask(
                    task_id=str(uuid.uuid4()),
                    task_type="diagnose_error",
                    payload={
                        "error_message": error_context,
                        "context": failed_task_desc
                    },
                    origin_agent="recovery_agent",
                    target_agent="debugging_agent"
                )
                debug_result = await self.bus.dispatch(debug_task)
                if debug_result and debug_result.success:
                    data["action"] = "retry"
                    data["debug_notes"] = debug_result.result
                else:
                    data["action"] = "escalate"
                    data["reason"] = f"Debug failed: {getattr(debug_result, 'error', 'unknown')}"
                data["dispatched"] = "debugging_agent"

            elif action == "replan":
                import uuid
                replan_task = AgentTask(
                    task_id=str(uuid.uuid4()),
                    task_type="replan",
                    payload={
                        "goal": goal or payload.get("goal", ""),
                        "failed_task": {"description": failed_task_desc},
                        "error": error_context
                    },
                    origin_agent="recovery_agent",
                    target_agent="planning_agent"
                )
                replan_result = await self.bus.dispatch(replan_task)
                if replan_result and replan_result.success:
                    data["new_plan"] = replan_result.result.get("plan", [])
                else:
                    data["action"] = "escalate"
                    data["reason"] = f"Replan failed: {getattr(replan_result, 'error', 'unknown')}"
                data["dispatched"] = "planning_agent"
            
            elif action == "escalate":
                import uuid
                speak_task = AgentTask(
                    task_id=str(uuid.uuid4()),
                    task_type="speak",
                    payload={"text": f"I encountered an issue and need your guidance: {data.get('reason', '')}"},
                    origin_agent="recovery_agent",
                    target_agent="supervisor_agent"
                )
                try:
                    await self.bus.dispatch(speak_task)
                except Exception as speak_err:
                    logger.warning(f"RecoveryAgent: Escalation notification to supervisor_agent failed: {speak_err}")
                data["dispatched"] = "supervisor_agent"
                
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse LLM response: {e}")
