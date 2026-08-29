import logging
from typing import List, Dict, Any, Optional
from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult
from modules.planning.task_planner import TaskPlannerTools
from modules.task.state_manager import SubTask
from modules.planning.dag_compiler import DAGCompiler
from modules.planning.task_graph import TaskGraph, TaskNode, TaskStatus, RiskLevel
from modules.planning.replanner import Replanner, FailureDiagnosis
from modules.planning.risk_gate import RiskGate, RiskAssessment
from ai.agents.planning.web_pipeline import is_web_development_goal, compile_web_development_pipeline
from modules.execution.task_visibility_engine import TaskVisibilityEngine, ExecutionContext

logger = logging.getLogger("JARVIS.PlanningAgent")


class PlanningAgent(BaseAgent):
    """
    Decomposes goals into executable DAGs.
    Wraps TaskPlannerTools + DAGCompiler + TaskGraph + Replanner + RiskGate.
    """
    def __init__(self, memory_agent, bus):
        super().__init__(agent_id="planning_agent")
        self.memory_agent = memory_agent
        self.bus = bus
        memory_mgr = memory_agent.memory if hasattr(memory_agent, "memory") else None
        self.planner = TaskPlannerTools(memory=memory_mgr)
        self.replanner = Replanner(memory_manager=memory_mgr)
        self.risk_gate = RiskGate()
        self.bus.register(self.agent_id, self.handle)

        # Cached tool catalog
        self._cached_tools_str = None

    def _get_cached_tools_catalog(self, tools_list) -> str:
        """Introspects tools and caches a minimal prompt-friendly catalog string."""
        if not tools_list:
            return ""
            
        if self._cached_tools_str is not None:
            return self._cached_tools_str
            
        import inspect
        catalog_parts = []
        seen_tool_names = set()
        for toolset in tools_list:
            for name, attr in inspect.getmembers(toolset):
                if name.startswith("_") or name in ["safe_execute", "register_toolsets", "aclose", "setup", "handle", "dispatch"]:
                    continue
                
                if name in seen_tool_names:
                    continue
                
                if inspect.ismethod(attr):
                    if hasattr(attr, "__func__") and hasattr(attr.__func__, "__qualname__"):
                        original_class = attr.__func__.__qualname__.split(".")[0]
                        if original_class in ["BaseSkill", "BaseAgent", "BaseTool", "object", "AbstractBus", "JarvisToolset", "Toolset"]:
                            continue
                            
                is_tool = inspect.ismethod(attr) or hasattr(attr, "_func") or hasattr(attr, "__wrapped__") or type(attr).__name__ == "FunctionTool"
                if is_tool:
                    seen_tool_names.add(name)
                    desc = "No description"
                    if hasattr(attr, "info") and hasattr(attr.info, "description"):
                        desc = attr.info.description
                    else:
                        desc = getattr(attr, "__doc__", "") or getattr(attr, "description", "") or "No description"
                    desc = str(desc).strip().split('\n')[0]
                    if len(desc) > 80:
                        desc = desc[:77] + "..."
                    
                    try:
                        func = attr
                        if hasattr(attr, "_func"):
                            func = attr._func
                        elif hasattr(attr, "__wrapped__"):
                            func = attr.__wrapped__
                        sig = inspect.signature(func)
                        params = [p for p in sig.parameters.keys() if p not in ("self", "args", "kwargs")]
                        params_str = f" (Args: {', '.join(params[:5])})" if params else ""
                    except Exception:
                        params_str = ""
                        
                    catalog_parts.append(f"- '{name}': {desc}{params_str}")
                    
        self._cached_tools_str = "\n".join(catalog_parts)
        return self._cached_tools_str

    def _is_grounded_task(self, description: str) -> bool:
        """Determines if a task requires the grounded visual interaction layer."""
        import re
        desc_lower = description.lower().strip()
        
        terminal_exclusions = ["run_terminal_command", "run_shell_command", "python ", "powershell "]
        if any(w in desc_lower for w in terminal_exclusions):
            return False
            
        # Grounded tasks are specifically screen/UI interaction commands (e.g. click on 2nd button, select the blue icon)
        ui_interaction_patterns = [
            r'\b(?:1st|2nd|3rd|\d+th|first|second|third|fourth|last)\b',
            r'\b(?:click|tap|press|select|choose)\s+(?:on\s+)?(?:the\s+)?(?:[\w-]+\s+)*(?:button|icon|logo|menu|checkbox|radio|link)\b',
            r'\b(?:scroll\s+until|inspect\s+(?:the\s+)?(?:chart|image|diagram|screen)|look\s+at\s+the\s+screen)\b',
            r'\b(?:select|choose)\s+(?:the\s+)?(?:biggest|cheapest|highest|lowest)\b'
        ]
        
        return any(re.search(pattern, desc_lower) for pattern in ui_interaction_patterns)

    def _normalize_and_validate_plan(self, parsed_list: list) -> List[SubTask]:
        """Normalizes parsed steps to a canonical schema and validates dependencies, types, and cycle safety."""
        normalized_items = []
        task_ids = set()
        
        # 1. Normalize keys and validate types
        for idx, item in enumerate(parsed_list):
            if not isinstance(item, dict) or not item:
                logger.warning(f"Skipping empty or non-dict plan item: {item}")
                continue
                
            task_id = item.get("id", item.get("task_id", idx + 1))
            cmd_val = item.get("command", item.get("action", item.get("query", "")))
            description = item.get("task", item.get("description", item.get("task_description", item.get("task_name", item.get("name", cmd_val)))))
            depends_on = item.get("depends_on", item.get("dependencies", []))
            tool_name = item.get("tool_name", item.get("tool"))
            args = item.get("args", item.get("arguments", item.get("params", {})))

            if not tool_name and item.get("command"):
                tool_name = "execute_command"
                if not args:
                    args = {"command": item["command"]}

            if not tool_name:
                desc_lower = str(description).lower()
                if any(w in desc_lower for w in ["read", "view", "inspect", "cat"]):
                    tool_name = "read_local_file"
                elif any(w in desc_lower for w in ["write", "create", "generate"]):
                    tool_name = "create_file"
                else:
                    tool_name = "execute_command"
                    if not args:
                        args = {"command": str(description)}

            if tool_name in ["run_terminal_command", "execute_command"]:
                if not isinstance(args, dict):
                    args = {}
                if not args.get("command"):
                    args["command"] = item.get("command") or str(description)

            verify_type = item.get("verify_condition_type", item.get("verify_type"))
            verify_target = item.get("verify_target")
            
            try:
                task_id = int(task_id)
            except (ValueError, TypeError):
                raise ValueError(f"Task ID '{task_id}' must be an integer.")
                
            if not isinstance(description, str) or not description.strip():
                raise ValueError(f"Task description must be a non-empty string. Got: '{description}'")
                
            if not isinstance(depends_on, list):
                if depends_on is None:
                    depends_on = []
                else:
                    depends_on = [depends_on]
            try:
                depends_on = [int(d) for d in depends_on]
            except (ValueError, TypeError):
                raise ValueError(f"Dependencies must be a list of integers. Got: {depends_on}")
                
            if tool_name is not None and not isinstance(tool_name, str):
                tool_name = str(tool_name)
                
            if not isinstance(args, dict):
                args = {}
                
            if task_id in task_ids:
                raise ValueError(f"Duplicate Task ID detected: {task_id}")
            task_ids.add(task_id)
            
            ctx = TaskVisibilityEngine.classify(description.strip(), tool_name, args)
            args["execution_context"] = ctx.value

            normalized_items.append({
                "id": task_id,
                "description": description.strip(),
                "depends_on": depends_on,
                "tool_name": tool_name,
                "args": args,
                "verify_type": verify_type,
                "verify_target": verify_target,
                "execution_context": ctx.value
            })

            
        # 2. Validate dependency references exist
        for item in normalized_items:
            for dep in item["depends_on"]:
                if dep not in task_ids:
                    raise ValueError(f"Task {item['id']} depends on non-existent Task ID: {dep}")
                    
        # 3. Check for circular dependencies (DFS)
        adj = {item["id"]: item["depends_on"] for item in normalized_items}
        visited = {}
        
        def has_cycle(node):
            visited[node] = 1
            for neighbor in adj.get(node, []):
                state = visited.get(neighbor, 0)
                if state == 1:
                    return True
                elif state == 0:
                    if has_cycle(neighbor):
                        return True
            visited[node] = 2
            return False
            
        for node in adj:
            if visited.get(node, 0) == 0:
                if has_cycle(node):
                    raise ValueError(f"Circular dependency detected in plan involving Task {node}")
                    
        # 4. Programmatic special rules enforcement and patching
        for item in normalized_items:
            # Ordinal task visual routing enforcement
            if self._is_grounded_task(item["description"]):
                if item["tool_name"] in ["play_youtube", "play_video"]:
                    logger.info(f"Special Rule Enforcement: Nullified tool '{item['tool_name']}' for ordinal task: '{item['description']}'")
                    item["tool_name"] = None
                    item["args"] = {}
            
            # write_code tool argument validation
            if item["tool_name"] == "write_code":
                allowed_args = {}
                raw_args = item["args"]
                if "file_path" in raw_args:
                    allowed_args["file_path"] = raw_args["file_path"]
                elif "path" in raw_args:
                    allowed_args["file_path"] = raw_args["path"]
                    
                if "code" in raw_args:
                    allowed_args["code"] = raw_args["code"]
                elif "content" in raw_args:
                    allowed_args["code"] = raw_args["content"]
                elif "code_content" in raw_args:
                    allowed_args["code"] = raw_args["code_content"]
                    
                if "instruction" in raw_args:
                    allowed_args["instruction"] = raw_args["instruction"]
                elif "instructions" in raw_args:
                    allowed_args["instruction"] = raw_args["instructions"]
                    
            # speak / respond tool argument normalization
            if item["tool_name"] in ["speak", "respond", "say", "notify", "print_message"]:
                raw_args = item["args"]
                msg = raw_args.get("message") or raw_args.get("text") or raw_args.get("response") or raw_args.get("content") or item["description"]
                item["args"] = {"message": msg}

            # Path slashes normalization
            for k, v in item["args"].items():
                if isinstance(v, str) and (":" in v or "\\" in v) and "/" not in v:
                    item["args"][k] = v.replace("\\", "/")

        subtasks = []
        for item in normalized_items:
            is_grounded = self._is_grounded_task(item["description"])
            subtasks.append(SubTask(
                description=item["description"],
                task_id=item["id"],
                dependencies=item["depends_on"],
                tool_name=None if is_grounded else item["tool_name"],
                args={} if is_grounded else item["args"],
                verify_condition_type=item["verify_type"],
                verify_target=item["verify_target"],
                execution_mode="grounded" if is_grounded else "deterministic",
                grounding_hint={"collection_hint": item["description"]} if is_grounded else None
            ))
            
        return subtasks

    async def _generate_plan(self, goal: str, context_str: str) -> List[SubTask]:
        from container import ServiceContainer
        container = ServiceContainer.instance()
        tools_list = container.get_or_none("tools") if container else []
        
        dynamic_tools_str = self._get_cached_tools_catalog(tools_list)
        
        # Safely cap context length to avoid exceeding LLM context and TPM limits
        if context_str and len(context_str) > 3000:
            context_str = context_str[:3000] + "\n... [Context truncated for length]"
                    
        prompt = f"""
        You are JARVIS's Task Planner compiler. Given a high-level goal: "{goal}", compile a detailed step-by-step task plan to achieve it.
        
        Execution context to consider (including AGENT CAPABILITY NOTES and historical performance):
        {context_str}

        Available tools you can target:
        {dynamic_tools_str}
        
        PLANNING POLICY:
        - ORDINAL/GROUNDED TASKS: For identifying/clicking specific ordinal items (e.g. 2nd link), do not use automatic result tools (e.g. play_youtube). First search/navigate, then set tool_name=null and execution_mode=grounded so it's routed to visual layer.
        - DEVELOPER/SYSTEM: Use run_terminal_command or read_local_file instead of visual GUI tools. Paths must be absolute starting with 'd:/Jarvis/'.
        - SCRIPTS/EXTRACTIONS: Write a single, self-contained Python script via write_code for web extraction/database queries/file restructuring/desktop GUI. Execute via run_terminal_command.
        - JSON compliance: All string values (especially the 'code' argument in 'write_code') MUST be valid JSON strings with escaped newlines ('\\n') and quotes ('\\"').
        
        Break the goal down into a dependency-aware JSON array of subtasks.
        For each subtask, specify:
        - 'id': integer unique ID (starting at 1)
        - 'task': descriptive task string
        - 'tool_name': name of the tool to use (must be one of the tools listed above)
        - 'args': dict of arguments matching the tool signature
        - 'depends_on': list of IDs of tasks that must finish before this task starts (empty list if no dependencies)
        
        Ensure paths use forward slashes (e.g. d:/Jarvis/...) for cross-platform compatibility.
        Return ONLY raw JSON, do not include markdown block formatting (do NOT wrap in ```json).
        """
        subtasks_response = await self.generate_response(prompt, response_mime_type="application/json")
        import re
        import json
        parsed = None
        # Try matching array first
        array_match = re.search(r'\[\s*\{.*\}\s*\]', subtasks_response, re.DOTALL)
        if array_match:
            try:
                parsed = json.loads(array_match.group(0))
            except Exception:
                pass
        # Try matching object next
        if not parsed:
            obj_match = re.search(r'\{\s*".*"\s*:\s*.*\}', subtasks_response, re.DOTALL)
            if obj_match:
                try:
                    parsed = json.loads(obj_match.group(0))
                except Exception:
                    pass
        if not parsed:
            try:
                parsed = self._parse_json_response(subtasks_response)
            except Exception as pe:
                logger.warning(f"Failed to parse subtask plan as JSON: {subtasks_response}. Error: {pe}")

        if not parsed or (isinstance(parsed, list) and not any(isinstance(x, dict) and x for x in parsed)):
            try:
                clean_prompt = f"Convert this text to a valid JSON array of tasks with 'id', 'task', 'tool_name', 'args', 'depends_on'. Output ONLY the raw JSON array.\nText:\n{subtasks_response}"
                clean_res = await self.generate_response(clean_prompt, response_mime_type="application/json")
                parsed = self._parse_json_response(clean_res)
            except Exception as e:
                logger.warning(f"Secondary JSON cleanup failed: {e}")

        if isinstance(parsed, dict):
            for k in ["subtasks", "tasks", "plan", "steps", "data"]:
                if k in parsed and isinstance(parsed[k], list):
                    parsed = parsed[k]
                    break
            else:
                parsed = [parsed]
        elif not isinstance(parsed, list):
            parsed = [parsed]

        # Guard against empty dicts or invalid lists
        valid_items = [x for x in parsed if isinstance(x, dict) and x]
        if not valid_items:
            logger.warning(f"No valid plan items parsed from LLM response for goal '{goal}'. Creating default subtask.")
            valid_items = [{"id": 1, "task": goal, "tool_name": "execute_command", "args": {"command": goal}, "depends_on": []}]
        parsed = valid_items

        logger.info(f"Subtasks raw response: {subtasks_response}")
        logger.info(f"Subtasks parsed response: {parsed}")
        subtasks = self._normalize_and_validate_plan(parsed)
        return DAGCompiler.compile_dependencies(subtasks)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type == "create_plan":
                goal = payload.get("goal", "")
                context_str = payload.get("context", "")
                
                # 1. Check static intent plan router first
                subtasks = self.planner.match_static_intent(goal)
                if subtasks:
                    logger.info(f"Fast Intent Plan Router matched goal: '{goal}'")
                # 2. Check professional 15-stage Web Development Workflow router
                elif is_web_development_goal(goal):
                    logger.info(f"PlanningAgent: Engaged 15-stage Web Development Pipeline for goal: '{goal}'")
                    subtasks = compile_web_development_pipeline(goal, context_str)
                else:
                    # 3. Dynamically generate general plan
                    subtasks = await self._generate_plan(goal, context_str)

                # Format as AgentPlan list (dictionaries)
                agent_plan = [st.__dict__ for st in subtasks]
                
                # Build TaskGraph representation
                task_graph = TaskGraph.from_subtasks(subtasks, goal=goal)
                layers = task_graph.get_parallel_layers()
                
                # Independent persistence step (exceptions caught internally)
                try:
                    self.planner.state_manager.set_plan(goal, subtasks)
                except Exception as p_err:
                    logger.error(f"PlanningAgent: Failed to persist plan: {p_err}")

                grounded_count = sum(1 for st in subtasks if st.execution_mode == "grounded")
                deterministic_count = len(subtasks) - grounded_count
                
                result_payload = {
                    "plan": agent_plan,
                    "task_graph": task_graph.to_dict(),
                    "parallel_layers_count": len(layers),
                    "metadata": {
                        "goal": goal,
                        "plan_version": 1,
                        "grounded_task_count": grounded_count,
                        "deterministic_task_count": deterministic_count,
                        "warnings": [],
                        "plan_confidence": 0.95
                    }
                }
                
                return self._create_result(task, success=True, result=result_payload)

            elif task_type == "create_task_graph":
                goal = payload.get("goal", "")
                context_str = payload.get("context", "")
                
                subtasks = self.planner.match_static_intent(goal)
                if not subtasks:
                    if is_web_development_goal(goal):
                        subtasks = compile_web_development_pipeline(goal, context_str)
                    else:
                        subtasks = await self._generate_plan(goal, context_str)

                task_graph = TaskGraph.from_subtasks(subtasks, goal=goal)
                
                # Assess risk for each node
                for node in task_graph.nodes.values():
                    assessment = self.risk_gate.evaluate_node(node)
                    node.risk_level = assessment.risk_level

                return self._create_result(task, success=True, result={
                    "task_graph": task_graph.to_dict(),
                    "layers": [[n.to_dict() for n in layer] for layer in task_graph.get_parallel_layers()]
                })

            elif task_type == "diagnose_and_replan":
                failed_task_dict = payload.get("failed_task", {})
                error = payload.get("error", "")
                goal = payload.get("goal", "")
                existing_graph_dict = payload.get("task_graph")

                if existing_graph_dict:
                    graph = TaskGraph.from_dict(existing_graph_dict)
                else:
                    active_subtasks = self.planner.state_manager.active_plan.subtasks if self.planner.state_manager.active_plan else []
                    graph = TaskGraph.from_subtasks(active_subtasks, goal=goal)

                failed_task_id = str(failed_task_dict.get("id", failed_task_dict.get("task_id", "1")))
                node = graph.get_node(failed_task_id)
                if not node:
                    node = TaskNode.from_dict(failed_task_dict)
                    graph.add_node(node)

                # Diagnose failure
                diagnosis = self.replanner.diagnose_failure(node, error)
                updated_graph, strategy = self.replanner.apply_recovery(graph, failed_task_id, diagnosis)

                return self._create_result(task, success=True, result={
                    "diagnosis": {
                        "category": diagnosis.category.value,
                        "root_cause": diagnosis.root_cause,
                        "strategy": strategy.value,
                        "suggested_fix": diagnosis.suggested_fix
                    },
                    "task_graph": updated_graph.to_dict()
                })

            elif task_type == "evaluate_plan_risk":
                plan_items = payload.get("plan", [])
                evaluations = []
                has_critical = False

                for item in plan_items:
                    node = TaskNode.from_dict(item)
                    assessment = self.risk_gate.evaluate_node(node)
                    if assessment.risk_level == RiskLevel.CRITICAL:
                        has_critical = True
                    evaluations.append({
                        "task_id": node.task_id,
                        "risk_level": assessment.risk_level.value,
                        "requires_approval": assessment.requires_approval,
                        "reason": assessment.reason
                    })

                return self._create_result(task, success=True, result={
                    "evaluations": evaluations,
                    "requires_overall_hitl": has_critical
                })
                
            elif task_type == "replan":
                failed_task = payload.get("failed_task", {})
                error = payload.get("error", "")
                goal = payload.get("goal", "")
                
                failed_desc = failed_task.get("description", failed_task.get("task", ""))
                failed_tool = failed_task.get("tool_name", failed_task.get("tool", ""))
                failed_args = failed_task.get("args", failed_task.get("arguments", {}))
                
                replan_hint = f"""
                --- FAILURE NOTICE ---
                The execution of the plan failed at a specific step:
                - Failed Step: "{failed_desc}"
                - Failed Tool: {failed_tool}
                - Args Used: {failed_args}
                - Execution Error: {error}
                
                Please generate a new plan that fixes or avoids this failure. Consider alternative tools or approaches.
                """
                
                dynamic_ctx = payload.get("context", "")
                context_str = f"{replan_hint}\n\n{dynamic_ctx}"
                
                try:
                    subtasks = await self._generate_plan(goal, context_str)
                    agent_plan = [st.__dict__ for st in subtasks]
                    task_graph = TaskGraph.from_subtasks(subtasks, goal=goal)
                    
                    try:
                        self.planner.state_manager.set_plan(goal, subtasks)
                    except Exception as p_err:
                        logger.error(f"PlanningAgent: Failed to persist replan: {p_err}")

                    grounded_count = sum(1 for st in subtasks if st.execution_mode == "grounded")
                    deterministic_count = len(subtasks) - grounded_count
                    
                    result_payload = {
                        "plan": agent_plan,
                        "task_graph": task_graph.to_dict(),
                        "metadata": {
                            "goal": goal,
                            "plan_version": 1,
                            "grounded_task_count": grounded_count,
                            "deterministic_task_count": deterministic_count,
                            "warnings": [],
                            "plan_confidence": 0.95
                        }
                    }
                    return self._create_result(task, success=True, result=result_payload)
                except Exception as e:
                    return self._create_result(task, success=False, error=f"Replan failed: {e}")
                
            else:
                return self._create_result(
                    task, 
                    success=False, 
                    error=f"PlanningAgent does not support task type '{task_type}'"
                )
        except Exception as e:
            logger.exception(f"PlanningAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))
