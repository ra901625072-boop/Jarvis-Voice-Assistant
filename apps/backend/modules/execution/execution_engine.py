import inspect
import asyncio
import logging
import os
from typing import List, Dict, Any, Callable
import contextvars
from modules.task.state_manager import AgentStateManager

current_task_type = contextvars.ContextVar('current_task_type', default='general')

logger = logging.getLogger("JARVIS.ExecutionEngine")

# Tool names that belong to shell/install category and require TIER_CONFIRM
_SHELL_TOOLS = frozenset({
    "install_software_package",
    "install_package",
    "run_shell_command",
    "execute_command",
    "run_terminal_command",
})

class ExecutionEngine:
    """
    ExecutionEngine dispatches parallel task execution nodes by routing
    them to the appropriate registered toolset methods.
    """
    def __init__(self, tools_list: List[Any] = None, security=None):
        self.tools: Dict[str, Callable] = {}
        self.state_manager = AgentStateManager()
        self.security = security  # Optional[SecurityManager]
        if tools_list:
            self.register_toolsets(tools_list)

    def register_toolsets(self, tools_list: List[Any]):
        """
        Dynamically inspects and registers all methods exposed by the toolsets.
        """
        for toolset in tools_list:
            toolset_class_name = toolset.__class__.__name__
            for name, attr in inspect.getmembers(toolset):
                # Skip private helper methods and system methods
                if name.startswith("_") or name in ["safe_execute", "register_toolsets", "aclose", "setup"]:
                    continue

                is_livekit_tool = attr.__class__.__name__ == "FunctionTool"
                is_method = inspect.ismethod(attr)

                if is_livekit_tool:
                    self.tools[name] = attr
                    logger.debug(f"Registered execution tool: {toolset_class_name}.{name}")
                elif is_method:
                    # Ensure we don't register internal base class methods (e.g. capture_screen, run_shell_command)
                    if hasattr(attr, "__func__") and hasattr(attr.__func__, "__qualname__"):
                        original_class = attr.__func__.__qualname__.split(".")[0]
                        if original_class in ["BaseSkill", "BaseAgent", "BaseTool", "object", "AbstractBus", "JarvisToolset", "Toolset"]:
                            continue
                    self.tools[name] = attr
                    logger.debug(f"Registered execution tool: {toolset_class_name}.{name}")
        logger.info(f"ExecutionEngine initialized with {len(self.tools)} executable tools.")

    async def dispatch(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """
        Dispatches execution of a tool name with its arguments.

        Security gate: shell/install tools require TIER_CONFIRM. If the caller
        does not pass confirmed=True in args, a warning string is returned and
        execution is blocked.
        """
        # Aliasing run_shell_command and execute_command to run_terminal_command
        if tool_name in ("run_shell_command", "execute_command"):
            tool_name = "run_terminal_command"
            if "cmd" in args:
                args["command"] = args.pop("cmd")

        # Aliasing install_software_package to install_package
        if tool_name == "install_software_package":
            tool_name = "install_package"

        # Conversational / messaging tool handling
        if tool_name in ("speak", "say", "respond", "notify", "print_message", "send_message"):
            msg = (
                args.get("message") or 
                args.get("text") or 
                args.get("response") or 
                args.get("content") or 
                args.get("msg") or 
                str(args)
            )
            logger.info(f"ExecutionEngine handled conversational tool '{tool_name}': {msg}")
            return str(msg)

        if tool_name not in self.tools:
            logger.error(f"Execution failure: tool '{tool_name}' is not registered.")
            raise ValueError(f"Tool '{tool_name}' is not supported by the execution engine.")

        # ── TIER_CONFIRM gate for shell/install tools ─────────────────────────
        if self.security and tool_name in _SHELL_TOOLS:
            confirmed = args.pop("confirmed", False)   # remove from args
            auto_confirm = getattr(self.security, "is_auto_confirm_enabled", lambda: False)() or os.environ.get("JARVIS_AUTO_CONFIRM", "true").lower() in ("true", "1", "yes")
            if not confirmed and not auto_confirm:
                from container import ServiceContainer
                approval_store = ServiceContainer.instance().get_or_none("approval_store") if ServiceContainer.instance() else None
                if approval_store:
                    import uuid
                    approval_id = approval_store.request(
                        task_id=str(uuid.uuid4()),
                        agent_id="execution_engine",
                        action=tool_name,
                        category="shell",
                        payload={"tool": tool_name, "args": args},
                        timeout=120.0,
                    )
                    
                    try:
                        from api.routes.websocket import notify_approval_pending
                        await notify_approval_pending(approval_id, tool_name)
                    except Exception as e:
                        logger.warning(f"Failed to notify UI of pending approval: {e}")

                    approved, reason = await approval_store.wait_for_approval(approval_id, timeout=120.0)
                    if not approved:
                        raise PermissionError(f"Action '{tool_name}' denied: {reason}")
                else:
                    raise PermissionError(f"Action '{tool_name}' requires confirmation but no approval store is available.")

        method = self.tools[tool_name]
        
        # Filter args to match method signature to prevent unexpected keyword argument TypeErrors
        filtered_args = args
        try:
            target_func = method
            if hasattr(method, "_func"):
                target_func = method._func
            elif hasattr(method, "__wrapped__"):
                target_func = method.__wrapped__
            sig = inspect.signature(target_func)
            valid_params = set(sig.parameters.keys())
            has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if not has_var_keyword:
                filtered_args = {k: v for k, v in args.items() if k in valid_params}
        except Exception:
            filtered_args = args

        # Log only arg keys to avoid leaking sensitive values (passwords, API keys)
        logger.info(f"Dispatching tool '{tool_name}' with args: {list(filtered_args.keys())}")

        # Execute method — wrap sync/async methods with timeout (default 600s) to prevent hangs
        tool_timeout = int(os.environ.get("JARVIS_TOOL_TIMEOUT", "600"))
        try:
            is_coro = (
                inspect.iscoroutinefunction(method) or 
                (hasattr(method, "__wrapped__") and inspect.iscoroutinefunction(method.__wrapped__)) or
                (hasattr(method, "_func") and inspect.iscoroutinefunction(method._func))
            )
            
            if is_coro:
                result = await asyncio.wait_for(method(**filtered_args), timeout=tool_timeout)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(method, **filtered_args), timeout=tool_timeout
                )

            is_tool_error = result is False or (
                isinstance(result, str) and (result.startswith("Error:") or result.startswith("Failed to") or result.startswith("Verification FAILED:"))
            )
            if is_tool_error:
                raise RuntimeError(result or "Tool execution failed.")

            logger.info(f"Tool '{tool_name}' finished execution. Result length: {len(str(result)) if result else 0}")
            return result
        except asyncio.TimeoutError:
            logger.error(f"Tool '{tool_name}' timed out after {tool_timeout} seconds.")
            raise TimeoutError(f"Tool '{tool_name}' exceeded the {tool_timeout}-second execution limit.")
        except Exception as e:
            logger.exception(f"Execution error running tool '{tool_name}': {e}")
            raise  # Bare raise preserves original traceback

