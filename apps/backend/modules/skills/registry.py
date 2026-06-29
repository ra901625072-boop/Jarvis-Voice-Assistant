import os
import importlib
import inspect
import logging
from typing import List, Any
from modules.skills.base_skill import BaseSkill

logger = logging.getLogger("JARVIS.Skills.Registry")

class SkillRegistry:
    """
    SkillRegistry scans the skills directory, dynamically imports skill modules,
    finds all subclasses of BaseSkill, and instantiates them with injected managers.

    NOTE: importlib.import_module is NOT thread-safe (it holds the GIL import lock).
    Skills are loaded sequentially to avoid deadlocks — the real speedup comes from
    the module-level FileManager singleton in base_skill.py (eliminates 15x DB inits).
    """
    def __init__(self, memory=None, security=None, room=None, verification=None):
        self.memory = memory
        self.security = security
        self.room = room
        self.verification = verification
        self.skills: List[BaseSkill] = []

    def load_skills(self) -> List[Any]:
        """Scans, imports, and instantiates skills in backend/modules/skills."""
        self.skills = []
        skills_dir = os.path.dirname(os.path.abspath(__file__))

        for filename in sorted(os.listdir(skills_dir)):
            if filename.endswith("_skill.py") and filename not in ("base_skill.py", "registry.py"):
                module_name = f"modules.skills.{filename[:-3]}"
                try:
                    module = importlib.import_module(module_name)
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if issubclass(obj, BaseSkill) and obj is not BaseSkill:
                            skill_instance = obj(
                                memory=self.memory,
                                security=self.security,
                                room=self.room,
                                verification=self.verification,
                            )
                            self.skills.append(skill_instance)
                            logger.info(f"Dynamically loaded skill: '{obj.__name__}' from '{filename}'")
                except Exception as e:
                    logger.error(
                        f"Failed to dynamically load skill module '{module_name}': {e}",
                        exc_info=True,
                    )

        logger.info(f"SkillRegistry loaded total of {len(self.skills)} skills.")
        return self.skills
