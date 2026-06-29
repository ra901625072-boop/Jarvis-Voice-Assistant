import logging
import json
import asyncio
from typing import Dict, Any

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.VerificationAgent")

class VerificationAgent(BaseAgent):
    """
    Quality gate before task closure.
    """
    def __init__(self, bus):
        super().__init__(agent_id="verification_agent")
        self.bus = bus
        self.bus.register(self.agent_id, self.handle)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type == "verify_task":
                return await self._handle_verify_task(task, payload)
            else:
                return self._create_result(task, success=False, error=f"VerificationAgent does not support task type '{task_type}'")
        except Exception as e:
            logger.exception(f"VerificationAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))

    async def _handle_verify_task(self, task: AgentTask, payload: dict) -> AgentResult:
        output = payload.get("output", "")
        expected = payload.get("expected_outcome", "")
        
        prompt = f"""
        You are JARVIS's Verification Engine.
        Analyze the execution output to determine if it meets the expected outcome.
        
        Expected Outcome: {expected}
        Execution Output: {output}
        
        Return JSON with exactly:
        - 'verified': boolean (true if passed, false if failed)
        - 'reason': string explaining the verification outcome
        """
        
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse LLM response: {e}")
