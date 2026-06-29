"""
toolsets/memory_tools.py — MemoryTools toolset.

All cognitive tools (set_active_goal, executive summary, goal management) are
consolidated here from the old VisionTools to fix the misplaced ownership issue
(Phase 3.6).
"""
import asyncio
from livekit.agents import llm
from tools.builtin.base import JarvisToolset
from modules.core.memory_manager import MemoryManager
from modules.core.security_manager import SecurityManager


class MemoryTools(JarvisToolset):
    """
    MemoryTools exposes options to read, update, and search conversational
    memories and agent state.

    SYSTEM PROMPT:
    Use MemoryTools to recall user preferences, project context, lessons
    learned, and store facts or episodic events. Retrieve project contexts
    before beginning work.

    SHORT DESCRIPTION:
    Manages semantic preferences, long-term memory retrieval, knowledge graph
    additions, self-reflection reports, and goal hierarchy tracking.

    PROCESS:
    1. Executes CRUD queries on user preference key-value storage.
    2. Searches chat histories semantically.
    3. Handles relational facts storage, reflection summaries, and goal status
       updates.

    FLOW:
    Agent -> Tool call -> MemoryManager -> DB collections / lifecycle memories
          -> Agent
    """

    def __init__(self, memory: MemoryManager, security: SecurityManager, room=None):
        super().__init__(security, room)
        self.memory = memory

    # ── Basic memory tools ───────────────────────────────────────────────────

    @llm.function_tool(description="Remember a preference or fact about the user for long-term storage")
    async def remember_preference(self, key: str, value: str) -> str:
        return await self.safe_execute(
            self.memory.set_preference, key, value, success_msg=f"Remembered that {key} is {value}."
        )

    @llm.function_tool(description="Retrieve a preference or fact about the user from long-term storage")
    async def get_preference(self, key: str) -> str:
        val = await self.safe_execute(self.memory.get_preference, key)
        if str(val).startswith("Error:"):
            return str(val)
        if val is None:
            return f"No preference found for {key}."
        return f"Preference for {key} is {val}."

    @llm.function_tool(description="Delete a preference or fact from long-term storage")
    async def delete_preference(self, key: str) -> str:
        deleted = await self.safe_execute(self.memory.delete_preference, key)
        if str(deleted).startswith("Error:"):
            return str(deleted)
        if deleted:
            return f"Deleted preference for {key}."
        return f"No preference found to delete for {key}."

    @llm.function_tool(description="Search conversation history semantically for specific keywords or topics")
    async def search_memory(self, query: str) -> str:
        results = await self.safe_execute(self.memory.search_history, query)
        if str(results).startswith("Error:"):
            return str(results)
        if not results:
            return f"No memories found matching '{query}'."
        formatted = f"Found {len(results)} matching memories:\n"
        for r in results:
            formatted += f"- [{r.get('timestamp','?')}] {r.get('role','?')}: {r.get('content','')[:120]}...\n"
        return formatted

    @llm.function_tool(description="Clear all conversation history. Requires user confirmation.")
    async def clear_history(self, confirmed: bool = False) -> str:
        return await self.safe_execute(
            self.memory.clear_history,
            confirmation_category="delete",
            confirmation_action="memory_history",
            confirmed=confirmed,
            success_msg="Conversation history cleared.",
        )

    @llm.function_tool(
        description=(
            "Explicitly store an important fact, experience, or skill into JARVIS long-term memory. "
            "Use memory_type='semantic' for facts, 'episodic' for past events, 'procedural' for "
            "how-to knowledge. Optionally specify the project (e.g., 'JARVIS', 'nova', 'react') "
            "to namespace the memory."
        )
    )
    async def store_memory(
        self, content: str, memory_type: str = "semantic", project: str = "general", importance: int = 7
    ) -> str:
        row_id = await self.safe_execute(
            self.memory.store_memory, content, memory_type, project, importance, None
        )
        if isinstance(row_id, str) and row_id.startswith("Error:"):
            return row_id
        return f"Memory stored (ID: {row_id}, type: {memory_type}, project: {project}, importance: {importance}/10)."

    @llm.function_tool(
        description=(
            "Search typed long-term memory for a query. Optionally filter by memory_type "
            "('semantic', 'episodic', 'procedural') and/or project name."
        )
    )
    async def search_typed_memory(
        self, query: str, memory_type: str = None, project: str = None
    ) -> str:
        results = await self.safe_execute(self.memory.search_memories, query, memory_type, project, 5)
        if isinstance(results, str) and results.startswith("Error:"):
            return results
        if not results:
            return f"No typed memories found matching '{query}'."
        lines = [f"Found {len(results)} memories:"]
        for r in results:
            lines.append(
                f"- [{r.get('memory_type', 'unknown')}][{r.get('project', 'unknown')}] "
                f"(imp:{r.get('importance', 5)}) {r.get('content', '')[:150]}..."
            )
        return "\n".join(lines)

    @llm.function_tool(
        description=(
            "Get all memories JARVIS has about a specific project (e.g., 'JARVIS', 'nova', 'react'). "
            "Use this to recall everything known about a project before starting work on it."
        )
    )
    async def get_project_context(self, project_name: str) -> str:
        res = await self.safe_execute(self.memory.get_project_context, project_name)
        return str(res)

    @llm.function_tool(
        description=(
            "Store a fact about how two things are related in JARVIS knowledge graph. "
            "Example: entity_a='Akshay', relation='builds', entity_b='JARVIS'."
        )
    )
    async def add_knowledge(self, entity_a: str, relation: str, entity_b: str) -> str:
        await self.safe_execute(self.memory.add_entity, entity_a, "concept", "")
        await self.safe_execute(self.memory.add_entity, entity_b, "concept", "")
        res = await self.safe_execute(self.memory.add_relationship, entity_a, relation, entity_b, 1.0)
        if isinstance(res, str) and res.startswith("Error:"):
            return res
        return f"Knowledge stored: {entity_a} → {relation} → {entity_b}."

    @llm.function_tool(
        description=(
            "Get recent JARVIS self-reflections — insights about user habits, workflow patterns, "
            "and lessons learned. Specify days (default 7) to look back."
        )
    )
    async def get_agent_reflections(self, days: int = 7) -> str:
        reflections = await self.safe_execute(self.memory.get_agent_reflections, days)
        if isinstance(reflections, str) and reflections.startswith("Error:"):
            return reflections
        if not reflections:
            return f"No reflections generated in the past {days} days."
        lines = [f"Agent Reflections (Past {days} days):"]
        for idx, r in enumerate(reflections, 1):
            lines.append(f"{idx}. [{r.get('period', 'daily')}] {r.get('created_at', '')[:10]}")
            lines.append(f"   {r.get('reflection', '')}")
            lines.append("")
        return "\n".join(lines)

    @llm.function_tool(
        description=(
            "Restore the last saved agent state after a restart or crash. "
            "Returns the previous goal and plan so JARVIS can resume where it left off."
        )
    )
    async def restore_agent_state(self) -> str:
        saved = await asyncio.to_thread(self.memory.restore_agent_state)
        if not saved:
            return "No saved agent state found. Starting fresh."
        goal = saved.get("current_goal", "Unknown")
        plan = saved.get("active_plan")
        saved_at = saved.get("saved_at", "unknown time")
        if plan:
            tasks = plan.get("subtasks", [])
            pending = [t["description"] for t in tasks if t.get("status") == "pending"]
            return (
                f"Restored state from {saved_at}.\n"
                f"Previous goal: {goal}\n"
                f"Pending tasks: {pending}"
            )
        return f"Restored state from {saved_at}. Previous goal: {goal}. No active plan."

    @llm.function_tool(
        description=(
            "Retrieve lessons JARVIS has learned from past failures and experience replay. "
            "Optionally filter by topic (e.g., 'selenium', 'google', 'download'). "
            "Use this before attempting a task that has previously failed."
        )
    )
    async def get_lessons_learned(self, topic: str = "") -> str:
        try:
            if topic:
                with self.memory._lock:
                    rows = self.memory.dbs["conversations"].execute(
                        """SELECT lesson, occurrence_count, last_triggered
                           FROM lessons_learned
                           WHERE lesson LIKE ? OR source_pattern LIKE ?
                           ORDER BY importance DESC, last_triggered DESC
                           LIMIT 5""",
                        (f"%{topic}%", f"%{topic}%"),
                    ).fetchall()
            else:
                with self.memory._lock:
                    rows = self.memory.dbs["conversations"].execute(
                        """SELECT lesson, occurrence_count, last_triggered
                           FROM lessons_learned
                           ORDER BY importance DESC, last_triggered DESC
                           LIMIT 8""",
                    ).fetchall()

            if not rows:
                return f"No lessons found{f' for topic: {topic}' if topic else ''}."
            lines = ["Lessons Learned:"]
            for lesson, count, last in rows:
                lines.append(f"\n[seen {count}x, last: {last[:10]}]\n  {lesson[:300]}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error retrieving lessons: {e}"

    @llm.function_tool(
        description=(
            "Get a summary of JARVIS's known capabilities, limitations, and confidence levels. "
            "Use this to understand what JARVIS can and cannot do before planning complex tasks."
        )
    )
    async def get_agent_self_model(self) -> str:
        ctx = await asyncio.to_thread(self.memory.lifecycle.get_self_model_context)
        if not ctx:
            return "Agent self-model not yet initialized."
        return ctx

    # ── Cognitive / Goal tools (moved from VisionTools per Phase 3.6) ────────

    @llm.function_tool(
        description=(
            "Set or update an active ROOT goal for JARVIS. Goals influence which memories are "
            "retrieved (goal-relevance scoring). Priority 1-10 (10=highest). Optionally specify "
            "project name. Goal type defaults to 'strategic' or 'project'."
        )
    )
    async def set_active_goal(
        self, goal: str, goal_type: str = "strategic", priority: int = 7, project: str = "general"
    ) -> str:
        goal_id = await asyncio.to_thread(
            self.memory.lifecycle.goal_memory.set_goal, goal, goal_type, None, priority, project
        )
        return f"Root Goal set (ID: {goal_id}): '{goal}' [{goal_type}, priority {priority}/10, project: {project}]."

    @llm.function_tool(
        description=(
            "Add a nested sub-goal to an existing goal. Use this to break down strategic goals "
            "into project/task/action goals. goal_type can be 'project', 'task', or 'action'."
        )
    )
    async def add_sub_goal(
        self, parent_id: int, goal: str, goal_type: str = "task", priority: int = 5
    ) -> str:
        goal_id = await asyncio.to_thread(
            self.memory.lifecycle.goal_memory.add_sub_goal, parent_id, goal, goal_type, priority
        )
        return f"Sub-goal set (ID: {goal_id}) under Parent {parent_id}: '{goal}' [{goal_type}]."

    @llm.function_tool(
        description=(
            "List all active goals JARVIS is currently tracking. "
            "Displays the full goal hierarchy (Strategic -> Project -> Task -> Action)."
        )
    )
    async def list_active_goals(self) -> str:
        context_str = await asyncio.to_thread(
            self.memory.lifecycle.goal_memory.goal_context_string
        )
        if not context_str:
            return "No active goals set. Use set_active_goal to add one."
        return context_str

    @llm.function_tool(
        description=(
            "Mark an active goal as completed or failed. This archives the goal to episodic memory "
            "for reflection. Use list_active_goals first to get the goal_id."
        )
    )
    async def complete_goal(self, goal_id: int, outcome: str = "completed") -> str:
        success = await asyncio.to_thread(
            self.memory.lifecycle.goal_memory.complete_goal, goal_id, outcome
        )
        if success:
            return f"Goal {goal_id} marked as '{outcome}' and archived to episodic memory."
        return f"Goal {goal_id} not found."

    @llm.function_tool(
        description=(
            "Get a performance report for all tools JARVIS has used. Shows success rates, average "
            "execution times, and reliability scores. Use this to identify unreliable tools before "
            "executing risky tasks."
        )
    )
    async def get_tool_performance(self) -> str:
        return await asyncio.to_thread(self.memory.lifecycle.tool_memory.get_all_tool_report)
