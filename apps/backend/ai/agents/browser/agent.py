"""
ai/agents/browser/agent.py — High-Level Autonomous Browser Agent for JARVIS.

Integrates with JARVIS MessageBus to coordinate browser automation, research, and interaction tasks
using the observe-reason-act-verify state machine and enterprise controller.
"""

import logging
import json
import asyncio
import time
from typing import Optional, Dict, Any

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult
from ai.agents.browser.schemas import BrowserActionSchema, AutomationWorkflowResult
from ai.agents.browser.state_machine import BrowserStateMachine
from modules.browser.controller import BrowserController

logger = logging.getLogger("JARVIS.BrowserAgent")


class BrowserAgent(BaseAgent):
    """
    Autonomous Browser Agent handling multi-step web automation, research, and interaction.
    """

    def __init__(self, bus, controller: Optional[BrowserController] = None):
        super().__init__(agent_id="browser_agent")
        self.bus = bus
        self.controller = controller or BrowserController()
        self.state_machine = BrowserStateMachine(
            controller=self.controller,
            llm_generator=self.generate_response,
        )
        self.bus.register(self.agent_id, self.handle)
        logger.info("BrowserAgent registered on MessageBus.")

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload or {}
        
        try:
            if task_type in ("automate_web_flow", "browse_and_interact", "browser_task"):
                return await self._handle_automate_web_flow(task, payload)
            elif task_type == "extract_page_content":
                return await self._handle_extract_page_content(task, payload)
            elif task_type == "close_task_tabs":
                return await self._handle_close_task_tabs(task, payload)
            else:
                return self._create_result(
                    task,
                    success=False,
                    error=f"BrowserAgent does not support task type '{task_type}'",
                )
        except Exception as e:
            logger.exception(f"BrowserAgent failed handling '{task_type}': {e}")
            return self._create_result(task, success=False, error=str(e))

    async def _handle_automate_web_flow(self, task: AgentTask, payload: dict) -> AgentResult:
        url = payload.get("url", "")
        instructions = payload.get("instructions", "") or payload.get("objective", "")
        max_steps = int(payload.get("max_steps", 10))
        time_budget = float(payload.get("time_budget_sec", 120.0))

        if not url and not instructions:
            return self._create_result(task, success=False, error="Both URL and instructions cannot be empty.")

        logger.info(f"BrowserAgent starting workflow for: '{instructions}' (URL: {url})")

        workflow_result: AutomationWorkflowResult = await self.state_machine.run(
            objective=instructions,
            initial_url=url if url else None,
            max_steps=max_steps,
            time_budget_sec=time_budget,
            task_id=task.task_id,
        )

        history_dicts = [h.dict() for h in workflow_result.history]

        if workflow_result.success:
            return self._create_result(
                task,
                success=True,
                result={
                    "actions_run": workflow_result.total_steps,
                    "final_url": workflow_result.final_url,
                    "final_title": workflow_result.final_title,
                    "history": history_dicts,
                },
            )
        else:
            return self._create_result(
                task,
                success=False,
                error=workflow_result.error or "Workflow execution failed.",
                result={"history": history_dicts, "actions_run": workflow_result.total_steps},
            )

    async def _handle_extract_page_content(self, task: AgentTask, payload: dict) -> AgentResult:
        url = payload.get("url", "")
        if not url:
            return self._create_result(task, success=False, error="Missing URL to extract.")

        await self.controller._ensure_driver()
        page = await self.controller.get_or_create_content_page(task_id=task.task_id)
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)

        observation = await self.controller.perception_engine.observe(page, tab_id=task.task_id)
        return self._create_result(
            task,
            success=True,
            result={
                "url": observation.url,
                "title": observation.title,
                "interactive_element_count": len(observation.interactive_elements),
                "a11y_node_count": len(observation.a11y_tree),
                "context_summary": observation.to_prompt_context(),
            },
        )

    async def _handle_close_task_tabs(self, task: AgentTask, payload: dict) -> AgentResult:
        task_id = payload.get("task_id", task.task_id)
        closed_count = 0
        for tab in self.controller.tab_manager.get_tabs_by_task(task_id):
            if not tab.protected:
                self.controller.tab_manager.unregister_tab(tab.tab_id)
                if not tab.page_ref.is_closed():
                    await tab.page_ref.close()
                    closed_count += 1

        return self._create_result(
            task,
            success=True,
            result={"closed_tabs": closed_count},
        )
