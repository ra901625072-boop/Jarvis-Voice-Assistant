import logging
from typing import Optional
from .world_state import WorldStateManager

logger = logging.getLogger("JARVIS.RecoveryEngine")

class RecoveryEngine:
    """
    Attempts deterministic recovery strategies for common failures.
    """
    def __init__(self, world_state: WorldStateManager):
        self.world_state = world_state
        
    def attempt_recovery(self, failed_task: str, error_reason: str) -> Optional[str]:
        """
        Analyzes the failure and world state to attempt a quick fix.
        Returns a description of the recovery directive, or None if no predefined recovery applies.
        """
        task_lower = failed_task.lower()
        error_lower = error_reason.lower()
        state = self.world_state.get_state_snapshot()
        
        logger.info(f"RecoveryEngine analyzing failure: {failed_task}")
        
        # Strategy 1: Browser crashed / not found
        if "browser" in task_lower or "chrome" in task_lower or "selenium" in task_lower:
            if "timeout" in error_lower or "not found" in error_lower or "crash" in error_lower:
                # Check if browser is actually running
                is_running = any("chrome" in p or "msedge" in p for p in state["processes"])
                if not is_running:
                    logger.info("Recovery Strategy: Browser is not running.")
                    return "Recovery Action: Browser process is dead. Explicitly launch the browser again before retrying the task."
                else:
                    logger.info("Recovery Strategy: Browser is running but unresponsive.")
                    return "Recovery Action: Browser is running but failed. Try focusing the window, checking for CAPTCHA manually, or restarting the browser process."
                    
        # Strategy 2: File locked or permission error
        if "file" in task_lower and ("locked" in error_lower or "permission" in error_lower or "access" in error_lower):
            return "Recovery Action: File is locked. Wait 3 seconds to let other processes release it, then retry."
            
        # Strategy 3: Window missing
        if "window" in task_lower and "not found" in error_lower:
            return "Recovery Action: Window not found. Use the world state manager to list actual open windows to find the exact title, then retry."

        return None
