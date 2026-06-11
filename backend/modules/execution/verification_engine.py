import logging
import os
from .world_state import WorldStateManager

logger = logging.getLogger("JARVIS.VerificationEngine")

class VerificationEngine:
    """
    Programmatically verifies the outcomes of tool executions.
    """
    def __init__(self, world_state: WorldStateManager):
        self.world_state = world_state
        
    def verify(self, condition_type: str, target: str) -> bool:
        """
        Programmatically verifies an outcome.
        
        Args:
            condition_type: One of 'process_running', 'window_exists', 'file_exists', 'clipboard_contains'
            target: The name of the process, window title, file path, or text snippet.
            
        Returns:
            bool: True if the condition is met, False otherwise.
        """
        condition_type = condition_type.lower()
        logger.info(f"Verifying: {condition_type} -> {target}")
        
        # Ensure we have the freshest state
        state = self.world_state.get_state_snapshot()
        
        if condition_type == "process_running":
            target_lower = target.lower()
            # Handle exact matches or partial if extension is provided
            return any(target_lower in p for p in state["processes"])
            
        elif condition_type == "window_exists":
            target_lower = target.lower()
            return any(target_lower in w["title"].lower() for w in state["windows"])
            
        elif condition_type == "file_exists":
            return os.path.exists(target)
            
        elif condition_type == "clipboard_contains":
            target_lower = target.lower()
            return target_lower in state["clipboard"].lower()
            
        else:
            logger.warning(f"Unknown verification condition: {condition_type}")
            return False
