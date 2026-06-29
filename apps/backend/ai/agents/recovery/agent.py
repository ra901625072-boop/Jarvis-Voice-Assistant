import logging
import json
import asyncio
from typing import Dict, Any

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.RecoveryAgent")

class RecoveryAgent(BaseAgent):
    """
    Handles failures autonomously.
    Decides whether to retry, replan, or escalate to user.
    """
    def __init__(self, bus):
        super().__init__(agent_id="recovery_agent")
        self.bus = bus
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
        
        prompt = f"""
        You are JARVIS's Recovery Engine.
        A task has failed in the execution DAG. Analyze the failure and provide a recovery directive.
        
        Task: {failed_task_desc}
        Error: {error_context}
        
        Return JSON with exactly:
        - 'action': string (one of: 'retry', 'replan', 'escalate')
        - 'reason': string explaining why this action was chosen
        - 'corrected_plan': string (if replan) or null
        """
        
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse LLM response: {e}")
