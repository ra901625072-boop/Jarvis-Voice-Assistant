import os
import platform
import string
import logging
from typing import Optional

logger = logging.getLogger("JARVIS.Security")

class SecurityManager:
    """
    SecurityManager enforces safe operations and checks commands against policy tiers.

    SYSTEM PROMPT:
    Query SecurityManager before executing potentially destructive commands to verify if confirmation or blockage is required.

    SHORT DESCRIPTION:
    Validates user commands and tool invocations against safety tiers (SAFE, CONFIRM, FORBIDDEN) and pre-flight target constraints.

    PROCESS:
    1. Reads category types of incoming system tasks.
    2. Determines tier restrictions (e.g. system restarts or deletions require confirmation; registry modifications are forbidden).
    3. Triggers target-specific block validation checks (e.g. preventing path operations inside System32).
    4. Raises PermissionError or flags confirmation signals.

    FLOW:
    Caller -> requires_confirmation() / pre_flight_check() -> policy lookup -> boolean verdict or PermissionError -> Caller
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
        
        "shell": TIER_CONFIRM,
        "install": TIER_CONFIRM,
        
        "registry": TIER_FORBIDDEN,
        "security_bypass": TIER_FORBIDDEN,
    }

    def __init__(self, settings: dict = None):
        self.settings = settings or {}
        logger.info("SecurityManager initialized with explicit policy matrix.")

    def get_tier(self, category: str) -> int:
        return self.POLICY_MATRIX.get(category.lower(), self.TIER_CONFIRM)

    def requires_confirmation(self, category: str, action: str) -> bool:
        tier = self.get_tier(category)
        if tier == self.TIER_FORBIDDEN:
            logger.warning(f"BLOCKED: Action '{action}' in category '{category}' is strictly forbidden.")
            raise PermissionError(f"Security policy forbids action: {action}")
            
        return tier == self.TIER_CONFIRM

    # ── Path safety ───────────────────────────────────────────────────────────
    # Centralised check replacing the old fs_utils.is_safe_path(). All code
    # that performs filesystem operations must go through this method.

    @staticmethod
    def _get_drives() -> list:
        """Return all available drive root paths on Windows."""
        drives = []
        if platform.system() == "Windows":
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    drives.append(drive)
        else:
            drives = ["/"]
        return drives

    def is_safe_path(self, path: str) -> bool:
        """
        Return True if the path is safe to operate on.

        Blocks:
          - Drive roots (e.g. C:\\)
          - Windows system directories (Windows, Program Files, System32, …)
          - Recycle Bin, Recovery, Boot
        """
        try:
            path = os.path.normpath(os.path.abspath(path))
            path_lower = path.lower()

            system_drive = os.environ.get("SystemDrive", "C:") + "\\"
            system_drive_lower = system_drive.lower()

            unsafe_prefixes = [
                os.path.join(system_drive_lower, "windows"),
                os.path.join(system_drive_lower, "program files"),
                os.path.join(system_drive_lower, "program files (x86)"),
                os.path.join(system_drive_lower, "system volume information"),
                os.path.join(system_drive_lower, "$recycle.bin"),
                os.path.join(system_drive_lower, "recovery"),
                os.path.join(system_drive_lower, "boot"),
            ]

            # Block bare drive roots
            drive_roots = [d.lower() for d in self._get_drives()]
            if path_lower in drive_roots:
                return False

            for prefix in unsafe_prefixes:
                if path_lower.startswith(prefix):
                    return False

            if path_lower in ("c:\\", "c:"):
                return False

            return True
        except Exception as e:
            logger.error(f"Error checking safety of path '{path}': {e}")
            return False

    def pre_flight_check(self, category: str, target: str) -> bool:
        """
        Pre-flight check before executing a tool.

        For filesystem categories (delete, move, rename) the target path is
        validated against the system-directory blocklist via is_safe_path().
        Returns False (and logs a warning) if the operation should be blocked.
        """
        if category in ("delete", "move", "rename", "copy") and target:
            if not self.is_safe_path(target):
                logger.warning(
                    f"Pre-flight check FAILED: attempt to operate on protected path: {target}"
                )
                return False
        return True

    def enforce_tier(self, category: str, action: str, confirmed: bool = False) -> Optional[str]:
        """
        Convenience helper for ExecutionEngine.dispatch().

        Returns:
          - None          if execution should proceed.
          - A warning str if TIER_CONFIRM and not confirmed.
        Raises PermissionError for TIER_FORBIDDEN.
        """
        tier = self.get_tier(category)
        if tier == self.TIER_FORBIDDEN:
            raise PermissionError(f"Security policy forbids action: {action}")
        if tier == self.TIER_CONFIRM and not confirmed:
            return (
                f"SECURITY WARNING: This action requires user confirmation. "
                f"Please ask the user to confirm they want to {action}. "
                f"Once they agree, call this tool again with confirmed=True."
            )
        return None

    def create_jwt(self, user_id: str, role: str) -> str:
        """Create a signed JWT token using python-jose."""
        from jose import jwt
        from datetime import datetime, timedelta, timezone
        secret = os.environ.get("JARVIS_API_KEY", "default_secret_key_change_me")
        payload = {
            "sub": user_id,
            "role": role,
            "exp": datetime.now(timezone.utc) + timedelta(days=7)
        }
        return jwt.encode(payload, secret, algorithm="HS256")

    def verify_jwt(self, token: str) -> dict:
        """Verify the JWT token and return the payload."""
        from jose import jwt, JWTError
        secret = os.environ.get("JARVIS_API_KEY", "default_secret_key_change_me")
        try:
            return jwt.decode(token, secret, algorithms=["HS256"])
        except JWTError as e:
            logger.error(f"JWT Verification failed: {e}")
            raise PermissionError("Invalid or expired authentication token")

    def check_permission(self, role: str, action: str) -> bool:
        """Role-Based Access Control check."""
        if role.lower() == "admin":
            return True
        # For non-admin, block forbidden actions
        try:
            category = action.split(":")[0] if ":" in action else action
            tier = self.get_tier(category)
            if tier == self.TIER_FORBIDDEN:
                return False
            return True
        except Exception:
            return False
