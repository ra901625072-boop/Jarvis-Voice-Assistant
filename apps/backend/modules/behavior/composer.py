"""
modules.behavior.composer
-------------------------
Dynamic prompt assembly pipeline and caching system for JARVIS system instructions.
"""

from typing import Optional, List, Dict, Any
import threading
import logging

from modules.behavior.persona import PersonaEngine, PersonaType
from modules.behavior.policies import BehaviorPolicy
from modules.behavior.modes import ModeManager, InteractionMode
from modules.behavior.agent_profiles import AgentBehaviorProfileRegistry

logger = logging.getLogger("JARVIS.Behavior.Composer")


class PromptComposer:
    """
    Assembles layered, contextual system prompts for JARVIS and its specialist agents.
    Provides thread-safe caching to avoid unnecessary string allocations.
    """

    def __init__(
        self,
        persona_engine: Optional[PersonaEngine] = None,
        mode_manager: Optional[ModeManager] = None,
    ):
        self.persona_engine = persona_engine or PersonaEngine()
        self.mode_manager = mode_manager or ModeManager()
        self._lock = threading.RLock()
        self._cached_prompt: Optional[str] = None
        self._cache_key: Optional[str] = None

    def invalidate_cache(self) -> None:
        """Clear cached system prompt."""
        with self._lock:
            self._cached_prompt = None
            self._cache_key = None

    def compose_system_prompt(
        self,
        mcp_context: Optional[str] = None,
        memory_context: Optional[str] = None,
        session_context: Optional[str] = None,
        language_preference: Optional[str] = None,
        status_board_context: Optional[str] = None,
        learned_patches: Optional[List[str]] = None,
        custom_instructions: Optional[List[str]] = None,
    ) -> str:
        """
        Dynamically compile the complete, layered system prompt for the primary JARVIS assistant.
        """
        with self._lock:
            # 1. Base Persona & Identity
            persona_block = self.persona_engine.build_persona_prompt_block()

            # 2. Behavioral Policies & Safety Guardrails
            policy_block = BehaviorPolicy.build_policies_prompt_block()

            # 3. Operational Interaction Mode
            mode_block = self.mode_manager.build_mode_prompt_block()

            sections = [
                persona_block,
                policy_block,
                mode_block,
            ]

            # 4. Contextual dynamic injections
            if mcp_context:
                sections.append(f"MCP TOOLS CONTEXT:\n{mcp_context.strip()}")

            if memory_context:
                sections.append(f"MEMORY & PREFERENCES CONTEXT:\n{memory_context.strip()}")

            if session_context:
                sections.append(f"SESSION HISTORY SUMMARY:\n{session_context.strip()}")

            if language_preference:
                sections.append(f"USER LANGUAGE PREFERENCE:\n{language_preference.strip()}")

            if status_board_context:
                sections.append(f"LIVE BACKGROUND TASKS STATUS:\n{status_board_context.strip()}")

            if learned_patches:
                patch_str = "\n".join(f"- {p}" for p in learned_patches)
                sections.append(f"LEARNED BEHAVIORAL ADJUSTMENTS (PROMPT PATCHES):\n{patch_str}")

            if custom_instructions:
                custom_str = "\n".join(f"- {c}" for c in custom_instructions)
                sections.append(f"ADDITIONAL OPERATIONAL DIRECTIVES:\n{custom_str}")

            full_prompt = "\n\n" + ("\n\n" + "-" * 40 + "\n\n").join(sections) + "\n"
            return full_prompt.strip()

    def compose_agent_prompt(
        self,
        agent_id: str,
        additional_context: Optional[str] = None,
        learned_patches: Optional[List[str]] = None
    ) -> str:
        """
        Compile a specialized system instruction for a specific agent swarm specialist.
        """
        base_agent_inst = AgentBehaviorProfileRegistry.build_agent_system_instruction(agent_id)
        sections = [base_agent_inst]

        # Add core policies relevant to all agents
        core_policy = (
            f"{BehaviorPolicy.MANDATORY_ACTION_POLICY}\n\n"
            f"{BehaviorPolicy.ANTI_HALLUCINATION_POLICY}\n\n"
            f"{BehaviorPolicy.SAFETY_POLICY}"
        )
        sections.append(f"CORE SYSTEM POLICIES:\n{core_policy}")

        if additional_context:
            sections.append(f"TASK & WORKSPACE CONTEXT:\n{additional_context.strip()}")

        if learned_patches:
            patch_str = "\n".join(f"- {p}" for p in learned_patches)
            sections.append(f"LEARNED PATCHES FOR {agent_id.upper()}:\n{patch_str}")

        return ("\n\n" + "-" * 40 + "\n\n").join(sections).strip()
