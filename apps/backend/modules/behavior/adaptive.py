"""
modules.behavior.adaptive
-------------------------
Adaptive behavior controller: connects the two-speed learning loop to dynamic prompt patching and autonomy adjustment.
"""

from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger("JARVIS.Behavior.Adaptive")


class AdaptiveBehaviorController:
    """
    Dynamically adjusts behavioral constraints, confirmation thresholds,
    and prompt patches based on real-time capability scores and learning recommendations.
    """

    def __init__(self, memory_manager=None, learning_orchestrator=None):
        self.mm = memory_manager
        self.orchestrator = learning_orchestrator
        self._active_patches: Dict[str, List[str]] = {}

    def register_prompt_patch(self, agent_id: str, patch_text: str) -> None:
        """Manually or programmatically register an active prompt patch for an agent or 'global'."""
        if agent_id not in self._active_patches:
            self._active_patches[agent_id] = []
        if patch_text not in self._active_patches[agent_id]:
            self._active_patches[agent_id].append(patch_text)
            logger.info(f"Registered dynamic prompt patch for '{agent_id}': {patch_text[:50]}...")

    def clear_prompt_patches(self, agent_id: Optional[str] = None) -> None:
        """Clear prompt patches for a specific agent or all agents."""
        if agent_id:
            self._active_patches.pop(agent_id, None)
        else:
            self._active_patches.clear()

    def get_active_patches(self, agent_id: str = "global") -> List[str]:
        """Retrieve all active prompt patches for an agent (including global patches)."""
        patches = list(self._active_patches.get("global", []))
        if agent_id != "global":
            patches.extend(self._active_patches.get(agent_id, []))
        return patches

    def evaluate_autonomy_level(self, agent_id: str, task_type: str) -> Dict[str, Any]:
        """
        Evaluate if an agent can execute autonomously or if it requires stricter confirmation.
        Uses EMA capability score and failure streaks from RealtimeLearner/CapabilityTracker.
        """
        if not self.mm:
            return {"autonomy_tier": "standard", "require_strict_confirmation": False, "score": 0.5}

        try:
            with self.mm._lock:
                row = self.mm.dbs["conversations"].execute(
                    """SELECT score, consecutive_failures FROM agent_capability_scores
                       WHERE agent_id = ? AND task_type = ?""",
                    (agent_id, task_type)
                ).fetchone()

                if row:
                    score, failures = float(row[0]), int(row[1])
                else:
                    score, failures = 0.5, 0

                # Determine autonomy policy
                if failures >= 2 or score < 0.4:
                    return {
                        "autonomy_tier": "restricted",
                        "require_strict_confirmation": True,
                        "score": score,
                        "consecutive_failures": failures,
                        "reason": f"High risk: score {score:.2f} with {failures} consecutive failures."
                    }
                elif score >= 0.85 and failures == 0:
                    return {
                        "autonomy_tier": "high_autonomy",
                        "require_strict_confirmation": False,
                        "score": score,
                        "consecutive_failures": 0,
                        "reason": f"High confidence: score {score:.2f}."
                    }
                else:
                    return {
                        "autonomy_tier": "standard",
                        "require_strict_confirmation": False,
                        "score": score,
                        "consecutive_failures": failures,
                        "reason": "Normal operational parameters."
                    }
        except Exception as e:
            logger.debug(f"Error evaluating autonomy level: {e}")
            return {"autonomy_tier": "standard", "require_strict_confirmation": False, "score": 0.5}
