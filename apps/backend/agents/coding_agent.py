import logging
import json
import asyncio
from typing import Dict, Any

from agents.base_agent import BaseAgent
from agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.CodingAgent")

class CodingAgent(BaseAgent):
    """
    Writes, modifies, and tests code.
    Absorbs CodingSkill, RefactoringSkill, ProjectBuilderSkill.
    """
    def __init__(self, bus, tools_list=None):
        super().__init__(agent_id="coding_agent")
        self.bus = bus
        self.tools_list = tools_list or []
        self.bus.register(self.agent_id, self.handle)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type == "write_code":
                return await self._handle_write_code(task, payload)
            elif task_type == "refactor_code":
                return await self._handle_refactor_code(task, payload)
            elif task_type == "build_project":
                return await self._handle_build_project(task, payload)
            else:
                return self._create_result(task, success=False, error=f"CodingAgent does not support task type '{task_type}'")
        except Exception as e:
            logger.exception(f"CodingAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))

    async def _handle_write_code(self, task: AgentTask, payload: dict) -> AgentResult:
        instruction = payload.get("instruction", "")
        file_path = payload.get("file_path", "")
        
        prompt = f"""
        You are a Coding Agent. 
        Write or modify the code based on the following instruction.
        Instruction: {instruction}
        File: {file_path}
        
        Return ONLY valid JSON with the following structure:
        {{
            "file_path": "{file_path}",
            "content": "the full raw code string to write to the file",
            "explanation": "brief explanation of what was written"
        }}
        """
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse LLM response: {e}")

    async def _handle_refactor_code(self, task: AgentTask, payload: dict) -> AgentResult:
        file_path = payload.get("file_path", "")
        goal = payload.get("refactoring_goal", "")
        content = payload.get("content", "")
        
        prompt = f"""
        Refactor the following code based on this target refactoring goal: "{goal}".
        Ensure all existing logic and edge cases are preserved, but structures are improved.
        
        File: {file_path}
        ```
        {content}
        ```
        
        Return a JSON response with exactly:
        - 'explanation': string describing the improvements
        - 'refactored_content': complete updated content of the file
        """
        
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse LLM response: {e}")

    async def _handle_build_project(self, task: AgentTask, payload: dict) -> AgentResult:
        description = payload.get("project_description", "")
        target_dir = payload.get("target_dir", "")
        
        prompt = f"""
        Create a new project scaffold for the following description:
        {description}
        
        Target Directory: {target_dir}
        
        Return a JSON object containing a list of files to create and initialization commands to run.
        {{
            "files": [
                {{"path": "relative/path/to/file", "content": "file content"}}
            ],
            "commands": [
                "npm init -y",
                "pip install -r requirements.txt"
            ]
        }}
        """
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse LLM response: {e}")
