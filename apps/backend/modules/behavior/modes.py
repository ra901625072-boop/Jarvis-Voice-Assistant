"""
modules.behavior.modes
----------------------
Contextual interaction modes for JARVIS (VoiceInteractive, BackgroundAutonomous, DeepResearch, Coding, SystemControl).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
import logging

logger = logging.getLogger("JARVIS.Behavior.Modes")


class InteractionMode(str, Enum):
    """Execution and interaction operational modes."""
    VOICE_INTERACTIVE = "voice_interactive"         # Real-time voice session with LiveKit
    BACKGROUND_AUTONOMOUS = "background_autonomous" # Silent background worker / DAG swarm execution
    DEEP_RESEARCH = "deep_research"                 # Multi-source web/document synthesis
    CODING = "coding"                               # Interactive software engineering & refactoring
    SYSTEM_CONTROL = "system_control"               # Step-by-step OS automation & UI interaction


@dataclass
class ModeBehaviorConfig:
    """Behavioral parameters for an operational mode."""
    mode: InteractionMode
    name: str
    description: str
    preferred_tools: List[str]
    max_voice_sentences: int
    allow_background_dispatch: bool
    strict_verification: bool
    guidelines: List[str] = field(default_factory=list)


class ModeManager:
    """
    Manages active operational modes and generates mode-specific system prompt guidelines.
    """

    DEFAULT_MODES: Dict[InteractionMode, ModeBehaviorConfig] = {
        InteractionMode.VOICE_INTERACTIVE: ModeBehaviorConfig(
            mode=InteractionMode.VOICE_INTERACTIVE,
            name="Voice Interactive Mode",
            description="Real-time spoken conversation over LiveKit WebRTC.",
            preferred_tools=["search_google_live", "launch_tool_in_background", "execute_goal"],
            max_voice_sentences=2,
            allow_background_dispatch=True,
            strict_verification=True,
            guidelines=[
                "Keep spoken responses strictly between 1 to 2 sentences.",
                "Immediately offload any heavy computation or multi-step action to background tools.",
                "Speak in natural Hinglish for verbal conversation, but maintain pure English for technical names and code."
            ]
        ),
        InteractionMode.BACKGROUND_AUTONOMOUS: ModeBehaviorConfig(
            mode=InteractionMode.BACKGROUND_AUTONOMOUS,
            name="Background Autonomous Swarm Mode",
            description="Autonomous DAG plan execution with minimal user interruption.",
            preferred_tools=["create_plan", "execute_plan", "verify_result", "recover_failure"],
            max_voice_sentences=0,
            allow_background_dispatch=True,
            strict_verification=True,
            guidelines=[
                "Execute tasks silently and update the status board after each milestone.",
                "Trigger automatic recovery pipelines on failure before escalating to user.",
                "Produce structured execution reports upon goal completion."
            ]
        ),
        InteractionMode.DEEP_RESEARCH: ModeBehaviorConfig(
            mode=InteractionMode.DEEP_RESEARCH,
            name="Deep Research Mode",
            description="Comprehensive investigation, fact-checking, and report synthesis.",
            preferred_tools=["research_topic", "search_google_live", "create_file"],
            max_voice_sentences=2,
            allow_background_dispatch=True,
            strict_verification=True,
            guidelines=[
                "Synthesize information from multiple verified sources.",
                "Structure output into detailed markdown documents with sections, tables, and citations.",
                "Save finalized research reports to disk via `create_file`."
            ]
        ),
        InteractionMode.CODING: ModeBehaviorConfig(
            mode=InteractionMode.CODING,
            name="Coding & Engineering Mode",
            description="High-precision code refactoring, bug fixing, and test generation.",
            preferred_tools=["refactor_code", "build_project", "diagnose_error", "verify_fix"],
            max_voice_sentences=1,
            allow_background_dispatch=False,
            strict_verification=True,
            guidelines=[
                "Verify existing code syntax and AST before applying surgical diffs.",
                "Always run unit tests to verify fixes.",
                "Never introduce breaking changes without documenting migration paths."
            ]
        ),
        InteractionMode.SYSTEM_CONTROL: ModeBehaviorConfig(
            mode=InteractionMode.SYSTEM_CONTROL,
            name="System & UI Control Mode",
            description="Grounded desktop automation and UI navigation.",
            preferred_tools=["click_screen_element", "automate_desktop_flow", "read_screen_text"],
            max_voice_sentences=1,
            allow_background_dispatch=False,
            strict_verification=True,
            guidelines=[
                "Observe screen state before and after every click or keystroke.",
                "Use bounding box and semantic label matching to locate UI targets.",
                "Abort immediately if unexpected system dialogs or errors appear."
            ]
        )
    }

    def __init__(self, default_mode: InteractionMode = InteractionMode.VOICE_INTERACTIVE):
        self._modes: Dict[InteractionMode, ModeBehaviorConfig] = dict(self.DEFAULT_MODES)
        self._active_mode: InteractionMode = default_mode

    @property
    def active_mode(self) -> ModeBehaviorConfig:
        return self._modes.get(self._active_mode, self.DEFAULT_MODES[InteractionMode.VOICE_INTERACTIVE])

    def set_mode(self, mode: InteractionMode) -> None:
        """Switch current operational mode."""
        if mode in self._modes:
            self._active_mode = mode
            logger.info(f"Interaction mode set to: {mode.value}")
        else:
            logger.warning(f"Unknown interaction mode '{mode}', keeping {self._active_mode.value}")

    def build_mode_prompt_block(self) -> str:
        """Generate system prompt section for the active interaction mode."""
        mode_cfg = self.active_mode
        guidelines_bullet = "\n".join(f"- {g}" for g in mode_cfg.guidelines)
        tools_str = ", ".join(f"`{t}`" for t in mode_cfg.preferred_tools)

        return (
            f"OPERATIONAL MODE: {mode_cfg.name.upper()}\n"
            f"Description: {mode_cfg.description}\n"
            f"Preferred Tools: {tools_str}\n"
            f"Mode Guidelines:\n{guidelines_bullet}"
        ).strip()
