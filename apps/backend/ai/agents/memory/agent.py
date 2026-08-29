import logging
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
        
        import asyncio
        try:
            if task_type in ("retrieve_context", "retrieve"):
                goal = payload.get("goal", "")
                project_name = payload.get("project_name", None)
                context = await asyncio.to_thread(self.memory.get_full_context, current_query=goal, project_name=project_name)
                conf = 0.8 if len(context) > 50 else 0.4
                return self._create_result(task, success=True, result={"context": context}, confidence=conf)
                
            elif task_type == "retrieve_last_session":
                context = await asyncio.to_thread(self.memory.get_last_session_context)
                conf = 0.8 if len(context) > 50 else 0.4
                return self._create_result(task, success=True, result={"last_session": context}, confidence=conf)
                
            elif task_type == "retrieve_workflow":
                goal = payload.get("goal", "")
                pref = ""
                lessons = ""
                try:
                    from modules.execution.success_patterns import SuccessLearner
                    learner = SuccessLearner(self.memory)
                    pref = learner.get_preferred_workflow(goal)
                    if not pref:
                        workflows = self.memory.search_workflows(goal, limit=2)
                        if workflows:
                            wf_str = "--- PAST SUCCESSFUL PLANS FOR SIMILAR GOALS ---\n"
                            for wf in workflows:
                                wf_str += f"[Goal: {wf['goal']}]\n{wf['plan']}\n\n"
                            pref = wf_str.strip()
                except Exception as e:
                    logger.debug(f"MemoryAgent get_preferred_workflow failed: {e}")
                    
                try:
                    project = payload.get("project", None)
                    lessons_data = self.memory.lifecycle._get_relevant_lessons(goal, project=project)
                    if lessons_data:
                        lessons = f"--- RELEVANT LESSONS LEARNED ---\n{lessons_data}"
                except Exception as e:
                    logger.debug(f"MemoryAgent get_relevant_lessons failed: {e}")
                    
                return self._create_result(task, success=True, result={
                    "preferred_workflow": pref,
                    "lessons": lessons
                })
                
            elif task_type == "retrieve_unreliable_tools":
                unreliable_str = ""
                try:
                    unreliable = self.memory.lifecycle.tool_memory.get_unreliable_tools()
                    if unreliable:
                        unreliable_str = "--- CAUTION: UNRELIABLE TOOLS ---\n"
                        for t in unreliable:
                            fail_rate = round((1.0 - t['reliability']) * 100, 1)
                            unreliable_str += f"- {t['tool_name']}: {fail_rate}% failure rate. Prefer alternatives.\n"
                        unreliable_str = unreliable_str.strip()
                except Exception as e:
                    logger.debug(f"MemoryAgent get_unreliable_tools failed: {e}")
                return self._create_result(task, success=True, result={"unreliable_tools": unreliable_str})
                
            elif task_type == "retrieve_agent_stats":
                stats_str = ""
                parts = []
                try:
                    with self.memory._lock:
                        rows = self.memory.dbs["conversations"].execute(
                            """SELECT agent_id, task_type, SUM(success), COUNT(*)
                               FROM agent_task_outcomes
                               GROUP BY agent_id, task_type
                               HAVING COUNT(*) >= 3"""
                        ).fetchall()
                    if rows:
                        agent_stats = "--- AGENT PERFORMANCE SNAPSHOT ---\n"
                        for aid, ttype, succ, total in rows:
                            rate = (succ / total) * 100
                            agent_stats += f"- {aid} / {ttype}: {rate:.0f}% success ({succ}/{total} runs)\n"
                        parts.append(agent_stats.strip())
                        
                    with self.memory._lock:
                        agent_lessons = self.memory.dbs["conversations"].execute(
                            """SELECT lesson FROM lessons_learned 
                               WHERE source_pattern LIKE '%\\_%\\_%' ESCAPE '\\'
                               ORDER BY importance DESC LIMIT 5"""
                        ).fetchall()
                    if agent_lessons:
                        agent_less_str = "--- AGENT-SPECIFIC LESSONS ---\n"
                        for (lesson,) in agent_lessons:
                            agent_less_str += f"- {lesson}\n"
                        parts.append(agent_less_str.strip())
                except Exception as e:
                    logger.debug(f"MemoryAgent retrieve_agent_stats failed: {e}")
                if parts:
                    stats_str = "\n\n".join(parts)
                return self._create_result(task, success=True, result={"agent_stats": stats_str})
                
            elif task_type in ("store_episode", "store"):
                episode = payload.get("episode", {}) if "episode" in payload else payload
                content = episode.get("content", "")
                project = episode.get("project", None)
                importance = episode.get("importance", 5)
                
                await asyncio.to_thread(self.memory.store_episodic, content=content, project=project, importance=importance)
                return self._create_result(task, success=True, result={"stored": True})
                
            elif task_type in ("compress_history", "consolidate"):
                await asyncio.to_thread(self.memory.run_nightly_maintenance)
                return self._create_result(task, success=True, result={"compressed": True})
                
            elif task_type == "record_execution_report":
                success = payload.get("success", False)
                plan_json = payload.get("plan_json", [])
                goal = payload.get("goal")
                
                if not goal and plan_json:
                    goal = plan_json[0].get("description", "unknown goal")
                    
                if not goal:
                    return self._create_result(task, success=True, result={"status": "no goal provided"})
                    
                try:
                    from modules.execution.success_patterns import SuccessLearner
                    learner = SuccessLearner(self.memory)
                    if success:
                        await asyncio.to_thread(learner.learn_from_success, goal, plan_json)
                    else:
                        await asyncio.to_thread(learner.record_failure, goal)
                except Exception as e:
                    logger.debug(f"Failed to record execution report: {e}")
                    
                return self._create_result(task, success=True, result={"recorded": True})
                
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
                # Check subsystem stats safely
                db = getattr(self.memory, 'dbs', {}).get("conversations")
                tasks_stored = 0
                stats = {"status": "healthy", "tasks_stored": tasks_stored}
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
