import logging
import json
import asyncio
from typing import Dict, Any

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.IntegrationAgent")

class IntegrationAgent(BaseAgent):
    """
    External API and service orchestration.
    Absorbs IntegrationSkill.
    """
    def __init__(self, bus):
        super().__init__(agent_id="integration_agent")
        self.bus = bus
        self.bus.register(self.agent_id, self.handle)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type in ("call_api", "call_rest_api"):
                return await self._handle_call_api(task, payload)
            elif task_type == "webhook_flow":
                return await self._handle_webhook_flow(task, payload)
            elif task_type == "call_graphql":
                return await self._handle_call_graphql(task, payload)
            elif task_type == "authenticate":
                return await self._handle_authenticate(task, payload)
            elif task_type == "connect_service":
                return await self._handle_connect_service(task, payload)
            elif task_type == "sync_data":
                return await self._handle_sync_data(task, payload)
            else:
                return self._create_result(task, success=False, error=f"IntegrationAgent does not support task type '{task_type}'")
        except Exception as e:
            logger.exception(f"IntegrationAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))

    async def _handle_call_api(self, task: AgentTask, payload: dict) -> AgentResult:
        service = payload.get("service", "")
        endpoint = payload.get("endpoint", "")
        params = payload.get("params", {})
        
        prompt = f"""
        You are JARVIS's Integration Agent.
        Construct the HTTP request details for the following API call:
        Service: {service}
        Endpoint: {endpoint}
        Parameters: {params}
        
        Return JSON with exactly:
        - 'method': HTTP method (e.g. GET, POST)
        - 'url': Full URL
        - 'headers': Key-value pairs for headers
        - 'body': JSON body (if applicable)
        """
        
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse LLM response: {e}")

    async def _handle_webhook_flow(self, task: AgentTask, payload: dict) -> AgentResult:
        # Generic webhook handling stub
        return self._create_result(task, success=True, result={"status": "handled", "payload": payload})

    async def _handle_call_graphql(self, task: AgentTask, payload: dict) -> AgentResult:
        return self._create_result(task, success=True, result={"status": "graphql_stub", "payload": payload})

    async def _handle_authenticate(self, task: AgentTask, payload: dict) -> AgentResult:
        return self._create_result(task, success=True, result={"status": "auth_stub", "payload": payload})

    async def _handle_connect_service(self, task: AgentTask, payload: dict) -> AgentResult:
        return self._create_result(task, success=True, result={"status": "connect_stub", "payload": payload})

    async def _handle_sync_data(self, task: AgentTask, payload: dict) -> AgentResult:
        return self._create_result(task, success=True, result={"status": "sync_stub", "payload": payload})
