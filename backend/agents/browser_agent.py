import logging
import json
import asyncio
from typing import Dict, Any

from agents.base_agent import BaseAgent
from agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.BrowserAgent")

class BrowserAgent(BaseAgent):
    """
    Browser automation and navigation logic.
    Absorbs BrowserAutomationSkill.
    """
    def __init__(self, bus, tools_list=None):
        super().__init__(agent_id="browser_agent")
        self.bus = bus
        self.tools_list = tools_list or []
        self.bus.register(self.agent_id, self.handle)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type == "automate_web_flow":
                return await self._handle_automate_web_flow(task, payload)
            else:
                return self._create_result(task, success=False, error=f"BrowserAgent does not support task type '{task_type}'")
        except Exception as e:
            logger.exception(f"BrowserAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))

    async def _handle_automate_web_flow(self, task: AgentTask, payload: dict) -> AgentResult:
        url = payload.get("url", "")
        instructions = payload.get("instructions", "")
        
        prompt = f"""
        You are JARVIS's Web Automation Engine.
        Fulfill the user's instructions: "{instructions}"
        Target URL: {url}
        
        Based on these instructions, output a JSON execution plan with a sequence of actions.
        Available action types:
        - "navigate": {{ "url": "..." }}
        - "click": {{ "selector": "..." }}
        - "type": {{ "selector": "...", "text": "..." }}
        
        Output JSON:
        {{
            "actions": [
                {{"type": "navigate", "url": "{url}"}},
                ...
            ]
        }}
        """
        
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse LLM response: {e}")
