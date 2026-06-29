"""
toolsets/task_tools.py — TaskTools toolset.

Manages background task listing, status queries, cancellation, and
launching tools in the background.
"""
import asyncio
import time
import uuid
import json
from livekit.agents import llm
from tools.builtin.base import JarvisToolset
from modules.core.security_manager import SecurityManager


class TaskTools(JarvisToolset):
    """
    TaskTools monitors and cancels long-running background tasks.

    SYSTEM PROMPT:
    Use TaskTools to track execution of asynchronous background processes
    (e.g. transfers, downloads). Inform users of current task status.

    SHORT DESCRIPTION:
    Exposes functions to query, list, and cancel background tasks.

    PROCESS:
    1. Reads background task details from the global TaskManager.
    2. Returns human-readable status, percent progress, or potential errors.
    3. Triggers cancellation sequences on active tasks.

    FLOW:
    Agent -> Tool call -> TaskManager -> Task status / cancellation -> Agent
    """

    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)

    @staticmethod
    def _get_task_manager():
        from container import ServiceContainer
        container = ServiceContainer.instance()
        if container:
            try:
                return container.get("task_manager")
            except KeyError:
                pass
        from modules.planning.task_manager import BackgroundTaskManager
        mgr = BackgroundTaskManager()
        mgr.start()
        return mgr

    @llm.function_tool(description="List all recent background tasks and their statuses")
    async def list_background_tasks(self, limit: int = 10) -> str:
        try:
            task_manager = self._get_task_manager()
            tasks = await asyncio.to_thread(task_manager.get_all_tasks, limit)
            lines = []
            if tasks:
                for t in tasks:
                    status = t.get("status", "unknown")
                    prog = t.get("progress", 0)
                    err = f", Error: {t['error']}" if t.get("error") else ""
                    lines.append(
                        f"- Task ID: {t['task_id']}, Type: {t['task_type']}, "
                        f"Status: {status}, Progress: {prog}%{err}"
                    )

            # Asyncio background tasks
            for t_id, t_info in list(_bg_tasks.items())[-limit:]:
                if t_id.startswith("bg_"):
                    status = t_info.get("status", "unknown")
                    err = f", Error: {t_info['error']}" if t_info.get("error") else ""
                    result = f", Result: {t_info['result']}" if t_info.get("result") else ""
                    lines.append(
                        f"- Task ID: {t_id}, Type: AsyncBackground, Status: {status}{result}{err}"
                    )

            if not lines:
                return "No background tasks have been registered yet."
            return "Recent background tasks:\n" + "\n".join(lines)
        except Exception as e:
            return f"Error retrieving tasks: {e}"

    @llm.function_tool(description="Get the detailed status of a specific background task by its ID")
    async def get_background_task_status(self, task_id: str) -> str:
        try:
            # Check asyncio background tasks first
            if task_id in _bg_tasks:
                t_info = _bg_tasks[task_id]
                status = t_info.get("status", "unknown")
                err = f"\nError: {t_info['error']}" if t_info.get("error") else ""
                res = f"\nResult: {t_info['result']}" if t_info.get("result") else ""
                return (
                    f"Task ID: {task_id}\nType: AsyncBackground\n"
                    f"Description: {t_info.get('description', '')}\n"
                    f"Status: {status}{res}{err}"
                )

            # Thread/SQLite tasks
            task_manager = self._get_task_manager()
            task = await asyncio.to_thread(task_manager.get_task, task_id)
            if not task:
                all_tasks = await asyncio.to_thread(task_manager.get_all_tasks, 100)
                for t in all_tasks:
                    if t["task_id"] == task_id:
                        status = t.get("status", "unknown")
                        prog = t.get("progress", 0)
                        err = f"\nError: {t['error']}" if t.get("error") else ""
                        res = f"\nResult: {t['result']}" if t.get("result") else ""
                        return (
                            f"Task ID: {task_id}\nType: {t['task_type']}\n"
                            f"Status: {status}\nProgress: {prog}%{res}{err}"
                        )
                return f"Task '{task_id}' not found."

            info = task.to_dict()
            err = f"\nError: {info['error']}" if info.get("error") else ""
            res = f"\nResult: {info['result']}" if info.get("result") else ""
            return (
                f"Task ID: {task_id}\nType: {info['task_type']}\n"
                f"Status: {info['status']}\nProgress: {info['progress']}%{res}{err}"
            )
        except Exception as e:
            return f"Error: {e}"

    @llm.function_tool(description="Cancel a running or queued background task by its ID")
    async def cancel_background_task(self, task_id: str) -> str:
        try:
            # Try asyncio tasks first
            if task_id in _bg_tasks:
                t_info = _bg_tasks[task_id]
                if t_info.get("status") == "running" and "task" in t_info:
                    t_info["task"].cancel()
                    t_info["status"] = "cancelled"
                    return f"Background task '{task_id}' was successfully cancelled."

            # Thread/SQLite tasks
            task_manager = self._get_task_manager()
            cancelled = await asyncio.to_thread(task_manager.cancel_task, task_id)
            if cancelled:
                return f"Task '{task_id}' was successfully cancelled."
            return (
                f"Could not cancel task '{task_id}'. It may not exist, or it has already "
                "completed, failed, or been cancelled."
            )
        except Exception as e:
            return f"Error: {e}"

    @llm.function_tool(
        description=(
            "Launch any registered tool in the background asynchronously. Returns a Task ID. "
            "You can continue handling other user commands while this runs."
        )
    )
    async def launch_tool_in_background(self, tool_name: str, tool_args_json: str = "") -> str:
        try:
            args = json.loads(tool_args_json) if tool_args_json else {}
        except Exception as e:
            return f"Error: Failed to parse tool_args_json: {e}"

        from container import ServiceContainer
        container = ServiceContainer.instance()
        tools_list = container.get("tools") if container else []

        if not tools_list:
            return "Error: Tools not available in ServiceContainer."

        from modules.execution.execution_engine import ExecutionEngine
        engine = ExecutionEngine(tools_list)
        task_id = f"bg_{uuid.uuid4().hex[:8]}"

        async def run_bg():
            return await engine.dispatch(tool_name, args)

        task = asyncio.create_task(run_bg())
        _bg_tasks[task_id] = {
            "description": f"Background tool {tool_name} with args {args}",
            "status": "running",
            "start_time": time.time(),
            "task": task,
        }

        def _done(t):
            try:
                res = t.result()
                _bg_tasks[task_id]["status"] = "completed"
                _bg_tasks[task_id]["result"] = str(res)
            except asyncio.CancelledError:
                _bg_tasks[task_id]["status"] = "cancelled"
            except Exception as e:
                _bg_tasks[task_id]["status"] = "failed"
                _bg_tasks[task_id]["error"] = str(e)

        task.add_done_callback(_done)
        return f"Successfully launched '{tool_name}' in the background. Task ID: {task_id}"
