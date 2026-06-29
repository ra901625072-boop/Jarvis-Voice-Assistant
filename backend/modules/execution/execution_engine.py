import inspect
import asyncio
import logging
from typing import List, Dict, Any, Callable, Optional
from modules.core.state_manager import AgentStateManager, AgentState

logger = logging.getLogger("JARVIS.ExecutionEngine")

# Tool names that belong to shell/install category and require TIER_CONFIRM
_SHELL_TOOLS = frozenset({
    "install_software_package",
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
            for name, attr in inspect.getmembers(toolset, predicate=inspect.ismethod):
                # Skip private helper methods and system methods
                if not name.startswith("_") and name not in ["safe_execute", "register_toolsets"]:
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
        if tool_name not in self.tools:
            logger.error(f"Execution failure: tool '{tool_name}' is not registered.")
            raise ValueError(f"Tool '{tool_name}' is not supported by the execution engine.")

        # ── TIER_CONFIRM gate for shell/install tools ─────────────────────────
        if self.security and tool_name in _SHELL_TOOLS:
            confirmed = args.get("confirmed", False)
            warning = self.security.enforce_tier(
                "shell", f"run shell tool '{tool_name}'", confirmed=confirmed
            )
            if warning:
                return warning

        method = self.tools[tool_name]
        # Log only arg keys to avoid leaking sensitive values (passwords, API keys)
        logger.info(f"Dispatching tool '{tool_name}' with args: {list(args.keys())}")

        # Execute method — wrap sync methods with timeout to prevent indefinite hangs
        try:
            if inspect.iscoroutinefunction(method):
                result = await asyncio.wait_for(method(**args), timeout=120)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(method, **args), timeout=120
                )

            logger.info(f"Tool '{tool_name}' finished execution. Result length: {len(str(result)) if result else 0}")
            return result
        except asyncio.TimeoutError:
            logger.error(f"Tool '{tool_name}' timed out after 120 seconds.")
            raise TimeoutError(f"Tool '{tool_name}' exceeded the 120-second execution limit.")
        except Exception as e:
            logger.exception(f"Execution error running tool '{tool_name}': {e}")
            raise  # Bare raise preserves original traceback

