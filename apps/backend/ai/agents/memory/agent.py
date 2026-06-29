import logging
from typing import Optional
from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.MemoryAgent")

class MemoryAgent(BaseAgent):
    """
    Decides what to remember, retrieve, compress, and forget.
    Wraps MemoryManager as an autonomous reasoning layer.
    """
    def __init__(self, memory, bus):
        super().__init__(agent_id="memory_agent")
        self.memory = memory
        self.bus = bus
        self.bus.register(self.agent_id, self.handle)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type in ("retrieve_context", "retrieve"):
                goal = payload.get("goal", "")
                context = self.memory.get_full_context(current_query=goal)
                return self._create_result(task, success=True, result={"context": context})
                
            elif task_type in ("store_episode", "store"):
                episode = payload.get("episode", {}) if "episode" in payload else payload
                content = episode.get("content", "")
                project = episode.get("project", None)
                importance = episode.get("importance", 5)
                
                self.memory.store_episodic(content=content, project=project, importance=importance)
                return self._create_result(task, success=True, result={"stored": True})
                
            elif task_type in ("compress_history", "consolidate"):
                self.memory.run_nightly_maintenance()
                return self._create_result(task, success=True, result={"compressed": True})
                
            elif task_type == "replay":
                goal = payload.get("goal", "")
                # experience_replay stub or call memory layer
                lessons = getattr(self.memory, 'lifecycle', None)
                if lessons and hasattr(lessons, '_get_relevant_lessons'):
                    res = lessons._get_relevant_lessons(goal)
                else:
                    res = "No replay available."
                return self._create_result(task, success=True, result={"replay": res})

            elif task_type == "memory_health_check":
                # Check subsystem stats
                stats = {"status": "healthy", "tasks_stored": len(getattr(self.memory, 'episodic_db', []))}
                return self._create_result(task, success=True, result=stats)
                
            else:
                return self._create_result(
                    task, 
                    success=False, 
                    error=f"MemoryAgent does not support task type '{task_type}'"
                )
        except Exception as e:
            logger.exception(f"MemoryAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))
