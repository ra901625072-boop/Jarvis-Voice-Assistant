"""toolsets/verification_tools.py — VerificationTools toolset."""
import asyncio
from livekit.agents import llm
from tools.builtin.base import JarvisToolset
from modules.execution.verification_engine import VerificationEngine
from modules.core.security_manager import SecurityManager


class VerificationTools(JarvisToolset):
    """
    VerificationTools contains actions for verifying command and tool outcomes.

    SYSTEM PROMPT:
    Always invoke VerificationTools immediately after executing critical state
    changes (e.g. file operations, application launching) to programmatically
    confirm success.

    SHORT DESCRIPTION:
    Provides programmatic verification functions to check system states such as
    processes, windows, files, or clipboard.

    PROCESS:
    1. Temporarily shifts the agent state to VERIFYING.
    2. Delegates verification check to VerificationEngine based on target
       condition types (process_running, file_exists, window_exists,
       clipboard_contains).
    3. Reverts agent state back to EXECUTING and returns confirmation string.

    FLOW:
    Agent -> verify_execution() -> AgentStateManager (State=VERIFYING)
          -> VerificationEngine -> Verification Result
          -> AgentStateManager (State=EXECUTING) -> Agent
    """

    def __init__(
        self,
        verification: VerificationEngine,
        security: SecurityManager,
        room=None,
    ):
        super().__init__(security, room)
        self.verification = verification

    @llm.function_tool(
        description=(
            "Programmatically verify the outcome of an action. "
            "MUST be called after taking an action like opening an app or creating a file to confirm success. "
            "condition_type: 'process_running', 'window_exists', 'file_exists', 'clipboard_contains'. "
            "target: process name (e.g., 'chrome'), window title, file path, or clipboard text."
        )
    )
    async def verify_execution(self, condition_type: str, target: str) -> str:
        from modules.core.state_manager import AgentStateManager, AgentState

        sm = AgentStateManager()
        sm.set_agent_state(AgentState.VERIFYING)

        result = await asyncio.to_thread(self.verification.verify, condition_type, target)

        sm.set_agent_state(AgentState.EXECUTING)

        if result:
            return f"Verification SUCCESS: {condition_type} -> '{target}' is TRUE."
        else:
            return f"Verification FAILED: {condition_type} -> '{target}' is FALSE."
