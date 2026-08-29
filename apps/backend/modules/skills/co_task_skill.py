import asyncio
import uuid
from typing import Dict
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill

# In-process registry of running tasks for the CoTaskSkill
_running_co_tasks: Dict[str, asyncio.Task] = {}

class CoTaskSkill(BaseSkill):
    """
    Skill for background/co-pilot task tracking ("remind me", "keep an eye on X").
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    async def _co_task_loop(self, task_id: str, description: str, interval: int):
        """Background loop for a co-task."""
        try:
            while True:
                await asyncio.sleep(interval)
                
                # Check status or perform the background action
                # For demonstration, we'll just log it or notify via room if possible.
                self.logger.info(f"Co-task update [{task_id}]: {description}")
                
                # If we have a room, we could send a data message to the frontend or LLM
                if self.room:
                    try:
                        msg = f'{{"type": "co_task_update", "task_id": "{task_id}", "description": "{description}"}}'
                        await self.room.local_participant.publish_data(msg.encode("utf-8"))
                    except Exception as e:
                        self.logger.error(f"Failed to publish co_task_update: {e}")

        except asyncio.CancelledError:
            self.logger.info(f"Co-task cancelled [{task_id}]")
        finally:
            if task_id in _running_co_tasks:
                del _running_co_tasks[task_id]

    @llm.function_tool(description="Start a lightweight background monitor or reminder task")
    async def start_co_task(self, description: str, check_interval_seconds: int = 60) -> str:
        """Start a background co-task."""
        async def _do_start():
            task_id = str(uuid.uuid4())[:8]
            loop_task = asyncio.create_task(self._co_task_loop(task_id, description, check_interval_seconds))
            _running_co_tasks[task_id] = loop_task
            
            return f"Started co-task '{task_id}': {description} (Checking every {check_interval_seconds}s)"

        return await self.safe_execute(
            _do_start,
            confirmation_category="read",
            confirmation_action=f"start co-task: {description}",
            confirmed=True,
            success_msg="Started co-task",
            error_msg="Failed to start co-task"
        )

    @llm.function_tool(description="Stop a running background co-task by its ID")
    async def stop_co_task(self, task_id: str) -> str:
        """Stop a running co-task."""
        async def _do_stop():
            if task_id in _running_co_tasks:
                _running_co_tasks[task_id].cancel()
                return f"Stopped co-task '{task_id}'."
            return f"Co-task '{task_id}' not found."

        return await self.safe_execute(
            _do_stop,
            confirmation_category="read",
            confirmation_action=f"stop co-task: {task_id}",
            confirmed=True,
            success_msg="Stopped co-task",
            error_msg="Failed to stop co-task"
        )

    @llm.function_tool(description="List all running background co-tasks")
    async def list_co_tasks(self) -> str:
        """List running co-tasks."""
        async def _do_list():
            if not _running_co_tasks:
                return "No running co-tasks."
            
            report = "Running co-tasks:\n"
            for tid in _running_co_tasks.keys():
                report += f"- {tid}\n"
            return report

        return await self.safe_execute(
            _do_list,
            confirmation_category="read",
            confirmation_action="list co-tasks",
            confirmed=True,
            success_msg="Listed co-tasks",
            error_msg="Failed to list co-tasks"
        )
