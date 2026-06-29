import logging
import json
import asyncio
from typing import Dict, Any

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.DebuggingAgent")

class DebuggingAgent(BaseAgent):
    """
    Autonomous error diagnosis and repair.
    Absorbs DebuggingSkill and SelfHealingSkill.
    """
    def __init__(self, bus):
        super().__init__(agent_id="debugging_agent")
        self.bus = bus
        self.bus.register(self.agent_id, self.handle)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type == "diagnose_error":
                return await self._handle_diagnose_error(task, payload)
            elif task_type == "apply_self_healing":
                return await self._handle_self_healing(task, payload)
            elif task_type == "verify_fix":
                return await self._handle_verify_fix(task, payload)
            else:
                return self._create_result(task, success=False, error=f"DebuggingAgent does not support task type '{task_type}'")
        except Exception as e:
            logger.exception(f"DebuggingAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))

    async def _handle_diagnose_error(self, task: AgentTask, payload: dict) -> AgentResult:
        error_context = payload.get("error_context", "")
        component_name = payload.get("component_name", "")
        
        prompt = f"""
        You are JARVIS, a senior software architect and debugging system.
        Analyze the following error context and diagnose the issue:
        
        {f"Component: {component_name}" if component_name else ""}
        Error Context:
        {error_context}
        
        Provide a detailed diagnostic report in JSON with exactly:
        - 'symptom': string describing what failed
        - 'root_cause': string explaining why it failed
        - 'proposed_fix': string with step-by-step instructions or code changes
        """
        
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse LLM response: {e}")

    async def _handle_self_healing(self, task: AgentTask, payload: dict) -> AgentResult:
        failed_task = payload.get("failed_task_description", "")
        error_message = payload.get("error_message", "")
        
        prompt = f"""
        A task failed and requires self-healing recovery.
        Task: {failed_task}
        Error: {error_message}
        
        Suggest a deterministic recovery sequence (e.g. rollback, retry, fallback action).
        Return JSON with exactly:
        - 'recovery_action': string describing the action to take
        - 'can_retry': boolean indicating if the task can be safely retried
        """
        
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse LLM response: {e}")

    async def _handle_verify_fix(self, task: AgentTask, payload: dict) -> AgentResult:
        test_command = payload.get("test_command", "")
        output = payload.get("execution_output", "")
        
        prompt = f"""
        Verify if the following test output indicates a successful repair.
        Test Command: {test_command}
        Output:
        {output}
        
        Return JSON with exactly:
        - 'is_fixed': boolean
        - 'reason': string explaining why
        """
        
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse LLM response: {e}")
