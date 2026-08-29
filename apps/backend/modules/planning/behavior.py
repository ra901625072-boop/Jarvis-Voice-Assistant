"""
modules.planning.behavior
-------------------------
Compatibility re-export layer for JARVIS behavior subsystem.
The core modular implementation now resides in `modules.behavior`.
"""

import logging
from modules.behavior import (
    JarvisBehavior,
    PersonaType,
    PersonaConfig,
    HinglishTemplates,
    PersonaEngine,
    BehaviorPolicy,
    InteractionMode,
    ModeBehaviorConfig,
    ModeManager,
    AgentBehaviorProfile,
    AgentBehaviorProfileRegistry,
    PromptComposer,
    AdaptiveBehaviorController,
)

logger = logging.getLogger("JARVIS.Behavior")

__all__ = [
    "JarvisBehavior",
    "PersonaType",
    "PersonaConfig",
    "HinglishTemplates",
    "PersonaEngine",
    "BehaviorPolicy",
    "InteractionMode",
    "ModeBehaviorConfig",
    "ModeManager",
    "AgentBehaviorProfile",
    "AgentBehaviorProfileRegistry",
    "PromptComposer",
    "AdaptiveBehaviorController",
]