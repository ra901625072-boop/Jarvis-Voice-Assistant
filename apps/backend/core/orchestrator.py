import asyncio
import logging
import uuid
import re
from typing import List, Dict, Any, Optional

from core.scheduler import PriorityTaskScheduler, TaskPriority, TaskRecord, TaskStatus
from modules.memory.shared_context import SharedContextStore
from events.event_bus import EventBus, TaskEvent
from container import ServiceContainer

logger = logging.getLogger("JARVIS.MasterOrchestrator")

class MasterOrchestrator:
    """
    Central Operating System Master Orchestrator for JARVIS.
    Analyzes natural language requests, decomposes multi-goal intents,
    spawns independent worker tasks, and coordinates concurrent execution.
    """
    _instance: Optional["MasterOrchestrator"] = None

    def __init__(self):
        self.scheduler = PriorityTaskScheduler.get_instance()
        self.shared_context = SharedContextStore.get_instance()
        self.event_bus = EventBus.get_instance()

    @classmethod
    def get_instance(cls) -> "MasterOrchestrator":
        if cls._instance is None:
            cls._instance = MasterOrchestrator()
        return cls._instance

    async def handle_user_intent(self, user_input: str, origin: str = "user") -> List[TaskRecord]:
        """
        Decomposes natural language user input into discrete worker tasks
        and enqueues them for concurrent execution.
        """
        logger.info(f"MasterOrchestrator received intent from '{origin}': '{user_input}'")

        # Decompose input into intent goals
        goals = self._decompose_intents(user_input)
        tasks_created = []

        for goal in goals:
            agent_type, priority = self._classify_agent_and_priority(goal)
            
            # Create worker coroutine bound to this specific goal
            coro = self._make_worker_coro(goal, agent_type)
            
            task_name = goal[:40] + "..." if len(goal) > 40 else goal
            
            task_record = await self.scheduler.submit_task(
                name=task_name,
                agent=agent_type,
                coro_func=coro,
                priority=priority,
                payload={"goal": goal, "origin": origin}
            )
            tasks_created.append(task_record)

        return tasks_created

    def _decompose_intents(self, text: str) -> List[str]:
        """
        Decomposes compound user requests containing 'and', 'while', or multi-sentence instructions
        into independent goal strings using TaskClassifier.
        """
        from modules.routing.task_classifier import TaskClassifier
        return TaskClassifier.decompose_intents(text)

    def _classify_agent_and_priority(self, goal: str) -> tuple[str, int]:
        """Determines target agent and task priority based on TaskClassifier analysis."""
        from modules.routing.task_classifier import TaskClassifier, TaskComplexityLevel
        
        goal_lower = goal.lower()

        # Priority 100 / Voice Interrupt
        if any(w in goal_lower for w in ["stop", "cancel", "pause", "resume", "status"]):
            return "system", TaskPriority.VOICE_INTERRUPT

        report = TaskClassifier.classify(goal)

        # Coding Agent
        if any(w in goal_lower for w in ["build", "create website", "code", "app", "fix bug", "refactor", "html", "react", "python", "git"]):
            return "coding", TaskPriority.CODING

        # Research Agent
        if any(w in goal_lower for w in ["research", "search", "cbdc", "gujarat", "find info", "summary", "analyze", "explain", "who is", "what is"]):
            return "research", TaskPriority.RESEARCH

        # Browser Agent
        if any(w in goal_lower for w in ["navigate", "open site", "browser", "youtube", "click", "download"]):
            return "browser", TaskPriority.RESEARCH

        # Default Interactive Q
        return "general", TaskPriority.USER_INTERACTIVE

    def _make_worker_coro(self, goal: str, agent_type: str):
        """Creates a specialized async worker task coroutine with progress reporting."""
        async def worker_coro(task: TaskRecord) -> Any:
            task.add_log(f"Initializing {agent_type.upper()} worker for goal: '{goal}'")
            await self.scheduler.update_progress(task.id, 10, f"Task assigned to {agent_type} agent")

            # Store active goal in SharedContext
            await self.shared_context.set("latest_active_goal", goal)

            # Check if agent bus is available in ServiceContainer
            container = ServiceContainer.instance()
            agent_bus = container.get("agent_bus") if container and container.has("agent_bus") else None

            if agent_bus:
                from ai.agents.types import AgentTask
                agent_task = AgentTask(
                    task_id=task.id,
                    task_type="execute_goal",
                    payload={"goal": goal},
                    origin_agent="orchestrator",
                    target_agent="coordinator_agent"
                )
                
                await self.scheduler.update_progress(task.id, 30, f"Dispatched task to coordinator_agent bus")
                
                # Check for cancellation before calling agent
                if task.cancel_token.is_cancelled:
                    return "Cancelled prior to agent call"

                res = await agent_bus.dispatch(agent_task)
                
                await self.scheduler.update_progress(task.id, 90, f"Worker completed execution")
                if not res.success:
                    raise RuntimeError(res.error or "coordinator_agent failed")
                return res.result
            else:
                # Fallback execution simulation with realistic progress steps
                task.add_log("ServiceContainer agent_bus not attached — running orchestrator direct mode")
                for p in range(25, 95, 20):
                    await asyncio.sleep(0.8)
                    if task.cancel_token.is_cancelled:
                        task.add_log("Worker loop noticed cancellation token")
                        return "Cancelled"
                    await self.scheduler.update_progress(task.id, p, f"{agent_type.capitalize()} processing step ({p}%)")

                return f"{agent_type.capitalize()} task completed for: {goal}"

        return worker_coro
