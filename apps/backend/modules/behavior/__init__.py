"""
modules.behavior
----------------
Production-grade modular behavior, persona, policy, prompt composition, and adaptation subsystem for JARVIS.
"""

from modules.behavior.persona import (
    PersonaType,
    PersonaConfig,
    HinglishTemplates,
    PersonaEngine,
)
from modules.behavior.policies import BehaviorPolicy
from modules.behavior.modes import (
    InteractionMode,
    ModeBehaviorConfig,
    ModeManager,
)
from modules.behavior.agent_profiles import (
    AgentBehaviorProfile,
    AgentBehaviorProfileRegistry,
)
from modules.behavior.composer import PromptComposer
from modules.behavior.adaptive import AdaptiveBehaviorController
from modules.behavior.facade import JarvisBehavior

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
