import logging
from typing import Optional

logger = logging.getLogger("JARVIS.Security")

class SecurityManager:
    """
    Enforces a strict policy matrix for destructive or sensitive actions.
    """
    
    TIER_SAFE = 0
    TIER_CONFIRM = 1
    TIER_FORBIDDEN = 2

    # Map categories to safety tiers
    POLICY_MATRIX = {
        "open": TIER_SAFE,
        "read": TIER_SAFE,
        "search": TIER_SAFE,
        "media": TIER_SAFE,
        
        "delete": TIER_CONFIRM,
        "move": TIER_CONFIRM,
        "rename": TIER_CONFIRM,
        "power": TIER_CONFIRM, # shutdown, restart, sleep
        "logout": TIER_CONFIRM,
        "close_app": TIER_CONFIRM,
        
        "registry": TIER_FORBIDDEN,
        "security_bypass": TIER_FORBIDDEN,
    }

    def __init__(self, settings: dict = None):
        self.settings = settings or {}
        logger.info("SecurityManager initialized with explicit policy matrix.")

    def get_tier(self, category: str) -> int:
        return self.POLICY_MATRIX.get(category.lower(), self.TIER_SAFE)

    def requires_confirmation(self, category: str, action: str) -> bool:
        tier = self.get_tier(category)
        if tier == self.TIER_FORBIDDEN:
            logger.warning(f"BLOCKED: Action '{action}' in category '{category}' is strictly forbidden.")
            raise PermissionError(f"Security policy forbids action: {action}")
            
        return tier == self.TIER_CONFIRM

    def pre_flight_check(self, category: str, target: str) -> bool:
        """
        Optional pre-flight checks before executing. 
        For example, checking if a critical system file is about to be deleted.
        """
        if category == "delete" and target:
            target_lower = target.lower()
            critical_dirs = ["c:\\windows", "c:\\program files", "system32"]
            for d in critical_dirs:
                if d in target_lower:
                    logger.warning(f"Pre-flight check failed: attempt to modify critical path: {target}")
                    return False
        return True
