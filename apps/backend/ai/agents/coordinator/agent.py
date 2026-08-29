import logging

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult
from modules.execution.world_state import WorldStateManager

logger = logging.getLogger("JARVIS.CoordinatorAgent")

class CoordinatorAgent(BaseAgent):
    """
    Selects which specialist agent(s) should handle a task.
    Coordinates multi-agent collaboration.
    Replaces cognitive_coordinator.py.
    """
    def __init__(self, bus, available_agents: list, memory_manager=None):
        super().__init__(agent_id="coordinator_agent")
        self.bus = bus
        self.available_agents = available_agents
        self.mm = memory_manager
        
        self.world_state = WorldStateManager()
        
        # Skills cache variables
        self._skills_cache = None
        self._skills_cache_mtime = 0
        
        # Validate memory manager interfaces in __init__
        self._has_cognitive_layer = False
        self._has_tool_memory = False
        self._has_workflow_stats = False
        
        if self.mm:
            self._has_cognitive_layer = True
            if hasattr(self.mm, 'lifecycle') and hasattr(self.mm.lifecycle, 'tool_memory') and hasattr(self.mm.lifecycle.tool_memory, 'get_unreliable_tools'):
                self._has_tool_memory = True
            else:
                logger.warning("Memory manager lacks standard tool_memory.get_unreliable_tools capability.")
                
            if hasattr(self.mm, 'get_workflow_stats'):
                self._has_workflow_stats = True
            else:
                logger.warning("Memory manager lacks get_workflow_stats capability.")
            
        self.bus.register(self.agent_id, self.handle)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type == "generate_context":
                return await self._handle_generate_context(task, payload)
            elif task_type == "evaluate_plan":
                return await self._handle_evaluate_plan(task, payload)
            elif task_type == "route_subtask":
                return await self._handle_route_subtask(task, payload)
            elif task_type == "execute_goal":
                return await self._handle_execute_goal(task, payload)
            else:
                return self._create_result(task, success=False, error=f"CoordinatorAgent does not support task type '{task_type}'")
        except Exception as e:
            logger.exception(f"CoordinatorAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))

    def _get_enabled_skills(self) -> list:
        """Retrieves enabled skills from catalog, utilizing memory cache."""
        import os
        import json
        
        curr_dir = os.path.abspath(os.path.dirname(__file__))
        while curr_dir and os.path.basename(curr_dir) != "backend":
            parent = os.path.dirname(curr_dir)
            if parent == curr_dir:
                break
            curr_dir = parent
        skills_file = os.path.join(curr_dir, "database", "skills.json")
        
        if not os.path.exists(skills_file):
            return []
            
        try:
            mtime = os.path.getmtime(skills_file)
            if self._skills_cache is None or mtime > self._skills_cache_mtime:
                with open(skills_file, "r", encoding="utf-8") as f:
                    skills_data = json.load(f)
                self._skills_cache = [s for s in skills_data.values() if s.get("enabled", True)]
                self._skills_cache_mtime = mtime
                logger.info(f"Loaded and cached {len(self._skills_cache)} enabled skills from {skills_file}")
            return self._skills_cache
        except Exception as e:
            logger.warning(f"Error reading skills.json: {e}")
            return self._skills_cache or []

    def _classify_subtask_mode(self, description: str) -> str:
        from modules.routing.task_classifier import TaskClassifier
        report = TaskClassifier.classify(description)
        if report.requires_grounded_vision:
            return "grounded"

        desc_lower = description.lower().strip()
        
        # Obvious deterministic / analytical / research patterns:
        deterministic_prefixes = [
            "open ", "run ", "start ", "launch ", "press ", "type ", "write ", "close ", "kill ",
            "research", "analyze", "analyse", "conduct", "create", "draft", "compile", "develop",
            "document", "summarize", "evaluate", "plan", "review", "generate", "design", "explain"
        ]
        if any(desc_lower.startswith(prefix) for prefix in deterministic_prefixes) or report.complexity_score <= 0.35:
            return "deterministic"
            
        return "unsure"

    async def _classify_subtask_mode_llm(self, description: str) -> str:
        prompt = f"""
        Classify the following task description as either "deterministic" or "grounded".
        - "deterministic": Simple, direct actions (e.g., opening an app, typing, pressing keys, simple hotkeys, basic tool execution) where pixel locations or visual searching/counting are not required.
        - "grounded": Tasks requiring vision, finding specific items, counting, scrolling to find an item, or choosing based on visual properties (colors, text, relative size).
        
        Task: "{description}"
        
        Return ONLY the string "deterministic" or "grounded".
        """
        try:
            response = await self.generate_response(prompt)
            resp = response.strip().lower()
            if "deterministic" in resp:
                return "deterministic"
            return "grounded"
        except Exception as e:
            logger.warning(f"LLM classification failed for '{description}': {e}. Defaulting to 'grounded' for safety.")
            return "grounded"

    async def _handle_route_subtask(self, task: AgentTask, payload: dict) -> AgentResult:
        description = payload.get("description", "")
        args = payload.get("args", {})
        
        mode = self._classify_subtask_mode(description)
        if mode == "unsure":
            mode = await self._classify_subtask_mode_llm(description)
            
        import uuid
        chain = getattr(task, "dispatch_chain", []) + [self.agent_id]
        
        # Check loop safety: if we have routed this task or query repeatedly
        if chain.count(self.agent_id) > 2 or len(chain) > 8:
            logger.warning(f"CoordinatorAgent: Routing loop detected (chain: {chain}). Falling back to grounded execution.")
            mode = "grounded"
            
        if mode == "grounded":
            logger.info(f"CoordinatorAgent routing grounded task: '{description}'")
            interaction_task = AgentTask(
                task_id=str(uuid.uuid4()),
                task_type="run_grounded_task",
                payload={
                    "description": description,
                    "args": args
                },
                origin_agent=self.agent_id,
                target_agent="interaction_agent",
                dispatch_chain=chain
            )
            res = await self.bus.dispatch(interaction_task)
            return self._create_result(task, success=res.success, result=res.result if res.success else None, error=res.error)
        else:
            logger.info(f"CoordinatorAgent routing deterministic task: '{description}'")
            tool_name = payload.get("tool_name")
            if not tool_name:
                desc_lower = description.lower()
                if "dir " in desc_lower or "list " in desc_lower or "find " in desc_lower:
                    tool_name = "execute_command"
                    if not args:
                        args = {"command": "dir D:\\CBDCP"}
                elif "read " in desc_lower or "cat " in desc_lower:
                    tool_name = "read_local_file"
                elif "create " in desc_lower or "write " in desc_lower or "report" in desc_lower:
                    tool_name = "create_file"
                else:
                    tool_name = "execute_command"
                    if not args:
                        args = {"command": "dir D:\\CBDCP"}

            subtask_data = {
                "id": 1,
                "description": description,
                "tool_name": tool_name,
                "args": args,
                "dependencies": [],
                "execution_mode": "deterministic"
            }
            exec_task = AgentTask(
                task_id=str(uuid.uuid4()),
                task_type="execute_plan",
                payload={
                    "plan": [subtask_data],
                    "goal": description
                },
                origin_agent=self.agent_id,
                target_agent="execution_agent",
                dispatch_chain=chain
            )
            res = await self.bus.dispatch(exec_task)
            return self._create_result(task, success=res.success, result=res.result if res.success else None, error=res.error)

    async def _handle_generate_context(self, task: AgentTask, payload: dict) -> AgentResult:
        goal = payload.get("goal", "")
        if not self._has_cognitive_layer:
            return self._create_result(task, success=True, result={"context": ""})
            
        project = "general"
        if hasattr(self, "mm") and self.mm and hasattr(self.mm, "_scorer") and hasattr(self.mm._scorer, "detect_project"):
            project = self.mm._scorer.detect_project(goal)

        import uuid
        tasks = []
        
        # 1. Retrieve Workflow & Lessons task
        tasks.append(AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="retrieve_workflow",
            payload={"goal": goal, "project": project},
            origin_agent=self.agent_id,
            target_agent="memory_agent",
            dispatch_chain=getattr(task, "dispatch_chain", []) + [self.agent_id]
        ))
        
        # 2. Retrieve Unreliable Tools task
        tasks.append(AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="retrieve_unreliable_tools",
            payload={},
            origin_agent=self.agent_id,
            target_agent="memory_agent",
            dispatch_chain=getattr(task, "dispatch_chain", []) + [self.agent_id]
        ))
        
        # 3. Retrieve Agent Stats task
        tasks.append(AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="retrieve_agent_stats",
            payload={"goal": goal, "project": project},
            origin_agent=self.agent_id,
            target_agent="memory_agent",
            dispatch_chain=getattr(task, "dispatch_chain", []) + [self.agent_id]
        ))
        
        # 4. Vision Screen State task (if room is active)
        room_active = False
        from container import ServiceContainer
        c = ServiceContainer.instance()
        room = c.get_or_none("room") if c else None
        if room and room.isconnected():
            room_active = True
            
        if room_active:
            tasks.append(AgentTask(
                task_id=str(uuid.uuid4()),
                task_type="analyze_screen",
                payload={"query": "Briefly describe the active window contents for context"},
                origin_agent=self.agent_id,
                target_agent="vision_agent",
                timeout_seconds=5.0,
                dispatch_chain=getattr(task, "dispatch_chain", []) + [self.agent_id]
            ))
            
        # Dispatch concurrently
        results = await self.bus.dispatch_many(tasks)
        
        # Map results by task_id to ensure safe lookup
        results_map = {}
        for idx, res in enumerate(results):
            if isinstance(res, Exception):
                if idx < len(tasks):
                    results_map[tasks[idx].task_id] = res
            elif hasattr(res, "task_id"):
                results_map[res.task_id] = res
        
        parts = []
        for task_sent in tasks:
            res = results_map.get(task_sent.task_id)
            if not res:
                logger.warning(f"No result returned for task {task_sent.task_type} ({task_sent.task_id})")
                continue
            if isinstance(res, Exception):
                logger.warning(f"Generate context task {task_sent.task_type} raised exception: {res}")
                continue
            if not res.success:
                logger.warning(f"Generate context task {task_sent.task_type} failed: {res.error}")
                continue
                
            if task_sent.task_type == "retrieve_workflow":
                pref = res.result.get("preferred_workflow")
                lessons = res.result.get("lessons")
                if pref:
                    parts.append(pref)
                if lessons:
                    parts.append(lessons)
            elif task_sent.task_type == "retrieve_unreliable_tools":
                unreliable_str = res.result.get("unreliable_tools")
                if unreliable_str:
                    parts.append(unreliable_str)
            elif task_sent.task_type == "retrieve_agent_stats":
                stats_str = res.result.get("agent_stats")
                if stats_str:
                    parts.append(stats_str)
            elif task_sent.task_type == "analyze_screen":
                analysis = res.result.get("analysis")
                if analysis:
                    parts.append(f"--- CURRENT SCREEN STATE ---\n{analysis}")
                    
        # Add World State (local system stats)
        try:
            ws = self.world_state.format_state_for_planner()
            parts.append(ws)
        except Exception as e:
            logger.debug(f"Coordinator world state failed: {e}")
            
        # Add Custom Skills Catalog
        try:
            enabled_skills = self._get_enabled_skills()
            if enabled_skills:
                catalog_parts = []
                catalog_parts.append("--- AVAILABLE CUSTOM SKILLS (Markdown-based instructions) ---")
                catalog_parts.append("If the user's intent matches any of these triggers, you should instruct the coordinator/planning agents to execute the custom skill by calling the run_custom_skill tool with the name of the skill and the user's request details.")
                for skill in enabled_skills:
                    name = skill.get("name", "Unnamed")
                    desc = skill.get("description", "No description")
                    triggers = skill.get("trigger", [])
                    if isinstance(triggers, list):
                        triggers_str = ", ".join(triggers)
                    else:
                        triggers_str = str(triggers)
                    catalog_parts.append(f"- Skill Name: {name}\n  Description: {desc}\n  Trigger keywords: {triggers_str}")
                parts.append("\n".join(catalog_parts))
        except Exception as e:
            logger.warning(f"Failed to inject custom skills into context: {e}")
            
        res_ctx = "--- EXECUTION CONTEXT ---\n" + "\n\n".join(parts) if parts else "No historical planning context available for this goal."
        return self._create_result(task, success=True, result={"context": res_ctx})

    async def _handle_evaluate_plan(self, task: AgentTask, payload: dict) -> AgentResult:
        goal = payload.get("goal", "")
        subtasks = payload.get("subtasks", payload.get("plan_descriptions", []))
        
        if not self._has_cognitive_layer:
            return self._create_result(task, success=True, result={"evaluation": "Plan accepted (cognitive layer disabled)."})
            
        warnings = []
        
        if self._has_tool_memory:
            try:
                unreliable = self.mm.lifecycle.tool_memory.get_unreliable_tools()
                unreliable_names = {t['tool_name'].lower() for t in unreliable}
                
                for subtask in subtasks:
                    task_lower = subtask.lower()
                    for bad_tool in unreliable_names:
                        if bad_tool in task_lower:
                            warnings.append(
                                 f"Risk: Task '{subtask}' appears to use '{bad_tool}', "
                                 f"which has a high historical failure rate."
                            )
            except Exception as e:
                logger.error(f"Error accessing unreliable tools from memory manager: {e}")
        else:
            logger.debug("Skipping unreliable tools check: memory capability unavailable.")
            
        if self._has_workflow_stats:
            try:
                stats = self.mm.get_workflow_stats(goal)
                if stats and stats.get('fail_count', 0) > 3 and stats.get('success_rate', 100.0) < 30.0:
                    last_err = stats.get('last_error', 'unknown')
                    warnings.append(
                        f"Risk: The goal pattern '{goal[:40]}...' historically fails {100-stats['success_rate']}% of the time. "
                        f"Last error: {last_err}"
                    )
            except Exception as e:
                logger.error(f"Error accessing workflow stats from memory manager: {e}")
        else:
            logger.debug("Skipping workflow stats check: memory capability unavailable.")

        eval_res = "PLAN WARNINGS:\n" + "\n".join(warnings) + "\nProceed with caution." if warnings else "Plan accepted. No known historical risks detected."
        return self._create_result(task, success=True, result={"evaluation": eval_res})

    async def _handle_execute_goal(self, task: AgentTask, payload: dict) -> AgentResult:
        goal = payload.get("goal", "")
        
        # Reset recovery attempts for new goal execution
        from modules.task.state_manager import AgentStateManager
        state_mgr = AgentStateManager()
        state_mgr.recovery_attempts = 0
        
        if not goal:
            return self._create_result(task, success=False, error="Goal is empty.")
            
        import uuid
        chain = getattr(task, "dispatch_chain", []) + [self.agent_id]

        # ── 1. Check Task Complexity & Intent first ───────────────────────────
        from modules.routing.intent_router import IntentRouter, QueryIntent
        from modules.routing.task_classifier import TaskComplexityLevel
        classification = IntentRouter.classify(goal)

        # Express Lane: Direct Chat, Factual Q&A, and Memory Lookups
        if classification.is_direct_chat:
            logger.info(f"CoordinatorAgent: Goal '{goal}' classified as direct chat ({classification.intent.value}). Executing express handler.")
            if classification.intent == QueryIntent.MEMORY_QUERY:
                reply_text = await IntentRouter.handle_direct_memory_query(
                    query=goal,
                    memory_manager=self.mm,
                    llm_generator_fn=self.generate_response
                )
            else:
                reply_text = await IntentRouter.handle_direct_conversation_or_qa(
                    query=goal,
                    llm_generator_fn=self.generate_response,
                    memory_context=""
                )
            return self._create_result(task, success=True, result={
                "result": reply_text,
                "plan": [{"id": 1, "task": "Direct response", "tool_name": "speak", "result": reply_text}]
            })

        # Express Lane: Atomic Single-Step Tool Actions (Level 2)
        if (
            classification.complexity_report
            and classification.complexity_report.complexity_level == TaskComplexityLevel.LEVEL_2_SINGLE_ACTION
            and classification.complexity_report.fast_subtasks
        ):
            logger.info(f"CoordinatorAgent: Goal '{goal}' matched fast atomic action. Dispatching directly to ExecutionAgent.")
            exec_task = AgentTask(
                task_id=str(uuid.uuid4()),
                task_type="execute_plan",
                payload={"plan": classification.complexity_report.fast_subtasks, "goal": goal},
                origin_agent=self.agent_id,
                target_agent="execution_agent",
                dispatch_chain=chain
            )
            exec_res = await self.bus.dispatch(exec_task)
            if exec_res.success:
                plan_out = exec_res.result.get("plan") if isinstance(exec_res.result, dict) and exec_res.result.get("plan") else classification.complexity_report.fast_subtasks
                top_result = exec_res.result.get("result") if isinstance(exec_res.result, dict) else None
                return self._create_result(task, success=True, result={
                    "status": "completed",
                    "goal": goal,
                    "result": top_result,
                    "evaluation": "Fast-path atomic action executed successfully.",
                    "plan": plan_out
                })
            else:
                return self._create_result(task, success=False, error=f"Atomic execution failed: {exec_res.error}")

        # ── 2. Deep Swarm Lane: Multi-step / Complex Goals ───────────────────
        # Step A: Generate Context
        logger.info(f"CoordinatorAgent: Generating context for complex goal '{goal}'")
        context_task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="generate_context",
            payload={"goal": goal},
            origin_agent=self.agent_id,
            target_agent=self.agent_id,
            dispatch_chain=chain
        )
        
        from modules.observability.trace import TraceSpan
        import threading
        from container import ServiceContainer
        ctx_span = TraceSpan(
            trace_id=context_task.task_id,
            agent_id=self.agent_id,
            task_type="generate_context"
        )
        
        # Dispatch via the bus!
        context_res = await self.bus.dispatch(context_task)
        
        ctx_span.finish(success=context_res.success, error=context_res.error)
        ctx_span.confidence = getattr(context_res, "confidence", 0.0)
        ctx_span.tokens_used = getattr(context_res, "tokens_used", 0)
        ctx_span.cost_usd = getattr(context_res, "cost_usd", 0.0)
        trace_store = ServiceContainer.instance().get_or_none("trace_store") if ServiceContainer.instance() else None
        if trace_store:
            trace_store.enqueue_save(ctx_span)

        context_str = ""
        if context_res.success:
            context_str = context_res.result.get("context", "")
            
        # 2. Create Plan via planning_agent
        logger.info(f"CoordinatorAgent: Creating plan for goal '{goal}'")
        planning_task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="create_plan",
            payload={"goal": goal, "context": context_str},
            origin_agent=self.agent_id,
            target_agent="planning_agent",
            dispatch_chain=chain
        )
        plan_res = await self.bus.dispatch(planning_task)
        if not plan_res.success:
            return self._create_result(task, success=False, error=f"Planning failed: {plan_res.error}")
        plan_json = plan_res.result.get("plan", [])
        if not plan_json:
            plan_json = [{
                "id": 1,
                "description": goal,
                "tool_name": "execute_command",
                "args": {"command": f"powershell -Command \"{goal}\""},
                "depends_on": [],
                "execution_mode": "deterministic"
            }]
            
        # 3. Evaluate Plan
        logger.info(f"CoordinatorAgent: Evaluating plan for goal '{goal}'")
        eval_task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="evaluate_plan",
            payload={"goal": goal, "subtasks": [t.get("description", t.get("task", "")) for t in plan_json]},
            origin_agent=self.agent_id,
            target_agent=self.agent_id,
            dispatch_chain=chain
        )
        
        eval_span = TraceSpan(
            trace_id=eval_task.task_id,
            agent_id=self.agent_id,
            task_type="evaluate_plan"
        )
        
        # Dispatch via the bus!
        eval_res = await self.bus.dispatch(eval_task)
        
        eval_span.finish(success=eval_res.success, error=eval_res.error)
        eval_span.confidence = getattr(eval_res, "confidence", 0.0)
        eval_span.tokens_used = getattr(eval_res, "tokens_used", 0)
        eval_span.cost_usd = getattr(eval_res, "cost_usd", 0.0)
        if trace_store:
            threading.Thread(target=trace_store.save, args=(eval_span,), daemon=True).start()

        eval_warning = eval_res.result.get("evaluation", "") if eval_res.success else ""
        logger.info(f"CoordinatorAgent: Plan evaluation warnings: {eval_warning}")
        
        # 4. Execute Plan via execution_agent
        logger.info(f"CoordinatorAgent: Executing plan for goal '{goal}'")
        exec_task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="execute_plan",
            payload={"plan": plan_json, "goal": goal},
            origin_agent=self.agent_id,
            target_agent="execution_agent",
            dispatch_chain=chain
        )
        exec_res = await self.bus.dispatch(exec_task)
        
        # 5. Return execution result payload normalized
        if exec_res.success:
            result_payload = {
                "status": "completed",
                "goal": goal,
                "evaluation": eval_warning,
                "plan": plan_json
            }
            return self._create_result(task, success=True, result=result_payload)
        else:
            return self._create_result(task, success=False, error=f"Execution failed: {exec_res.error}")
