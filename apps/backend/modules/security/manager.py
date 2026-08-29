import os
import platform
import string
import logging
from typing import Optional

from pathlib import Path
import tempfile
import hashlib

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
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        default_workspace = os.path.dirname(backend_dir)
        configured_workspace = os.environ.get("JARVIS_WORKSPACE_ROOT") or os.environ.get("JARVIS_MCP_FS_ROOT") or default_workspace
        self.workspace_root = Path(configured_workspace).resolve()
        
        drive = os.path.splitdrive(str(self.workspace_root))[0]
        self.allowed_drive = (drive.lower() + "\\") if drive else "d:\\"
        logger.debug(f"SecurityManager initialized. Workspace root: {self.workspace_root}")

    def get_tier(self, category: str) -> int:
        return self.POLICY_MATRIX.get(category.lower(), self.TIER_CONFIRM)

    def is_auto_confirm_enabled(self) -> bool:
        if self.settings and "auto_confirm" in self.settings:
            return bool(self.settings["auto_confirm"])
        auto_env = os.environ.get("JARVIS_AUTO_CONFIRM", "false").lower()
        return auto_env in ("true", "1", "yes")

    def requires_confirmation(self, category: str, action: str) -> bool:
        tier = self.get_tier(category)
        if tier == self.TIER_FORBIDDEN:
            logger.warning(f"BLOCKED: Action '{action}' in category '{category}' is strictly forbidden.")
            raise PermissionError(f"Security policy forbids action: {action}")
            
        if tier == self.TIER_CONFIRM and self.is_auto_confirm_enabled():
            logger.info(f"Auto-confirm enabled: Action '{action}' in category '{category}' auto-approved.")
            return False

        return tier == self.TIER_CONFIRM

    # ── Path safety ───────────────────────────────────────────────────────────
    # Centralised check replacing the old fs_utils.is_safe_path(). All code
    # that performs filesystem operations must go through this method.

    @staticmethod
    def _get_drives() -> list:
        """Return all available drive root paths on Windows."""
        drives = []
        if platform.system() == "Windows":
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            workspace_root = os.path.dirname(backend_dir)
            drive = os.path.splitdrive(workspace_root)[0]
            allowed_drive = (drive.lower() + "\\") if drive else "d:\\"
            
            if os.path.exists(allowed_drive):
                drives.append(allowed_drive)
            # Maintain backward compatibility if D:\ is also available and distinct
            if allowed_drive != "d:\\" and os.path.exists("D:\\"):
                drives.append("D:\\")
        else:
            drives = ["/"]
        return drives

    def is_safe_path(self, path: str, role: str = "user") -> bool:
        """
        Return True if the path is safe to operate on.
        Canonicalizes path and enforces that it resides strictly within
        the configured workspace root or temporary directory.
        Blocks bare drive roots, Windows/system paths, and traversal escapes.
        """
        if not path or not str(path).strip():
            return False
        try:
            target_path = Path(path).resolve()
            
            # Allow temp directory (for tests/scratch files)
            temp_dir = Path(tempfile.gettempdir()).resolve()
            try:
                target_path.relative_to(temp_dir)
                return True
            except ValueError:
                pass

            # Explicit check against system roots / Windows directories
            target_str = str(target_path).lower()
            if platform.system() == "Windows":
                # Check bare drive roots (e.g. C:\, D:\)
                drive_root = os.path.splitdrive(target_str)[0].rstrip("\\") + "\\"
                if target_str == drive_root or target_str.rstrip("\\") == os.path.splitdrive(target_str)[0].rstrip("\\"):
                    return False
                # System directories
                win_dir = os.environ.get("WINDIR", "C:\\Windows").lower()
                prog_files = os.environ.get("ProgramFiles", "C:\\Program Files").lower()
                prog_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)").lower()
                if target_str.startswith(win_dir) or target_str.startswith(prog_files) or target_str.startswith(prog_files_x86) or "$recycle.bin" in target_str:
                    return False
            else:
                if target_str in ("/", "/root", "/bin", "/sbin", "/etc", "/usr", "/lib", "/var"):
                    return False

            # Enforce workspace root containment
            try:
                target_path.relative_to(self.workspace_root)
                return True
            except ValueError:
                if target_path == self.workspace_root:
                    return True
                return False
        except Exception as e:
            logger.error(f"Error checking safety of path '{path}': {e}")
            return False

    def _get_jwt_secret(self) -> str:
        if hasattr(self, "_jwt_secret_cached") and self._jwt_secret_cached is not None:
            return self._jwt_secret_cached

        secret = os.environ.get("JARVIS_JWT_SECRET")
        is_testing = os.environ.get("TESTING") == "true"
        
        if not secret:
            api_key = os.environ.get("JARVIS_API_KEY")
            if api_key:
                secret = hashlib.sha256(api_key.encode()).hexdigest()
                logger.warning("JARVIS_JWT_SECRET not configured. Derived secret from JARVIS_API_KEY hash.")
            elif is_testing:
                secret = "test_environment_secure_jwt_secret_key_1234567890_32bytes"
                logger.info("TESTING mode active. Using ephemeral test JWT secret.")
            else:
                raise ValueError(
                    "CRITICAL SECURITY CONFIGURATION ERROR: JARVIS_JWT_SECRET environment variable is missing. "
                    "A strong secret key of at least 32 characters is required to start JARVIS in production mode."
                )

        INSECURE_SECRETS = {
            "your-super-secret-jwt-key-change-this-in-production",
            "your-super-secret-jwt-key-change-this-in-production-12345",
            "changeme",
        }
        if not is_testing and (secret in INSECURE_SECRETS or "change-this" in secret.lower()):
            raise ValueError(
                "CRITICAL SECURITY CONFIGURATION ERROR: JARVIS_JWT_SECRET is using an insecure default value. "
                "Set a unique 32+ character secret in production."
            )

        if len(secret) < 32 and not is_testing:
            raise ValueError("JARVIS_JWT_SECRET must be at least 32 characters in length.")

        self._jwt_secret_cached = secret
        return secret

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
        if tier == self.TIER_CONFIRM and not confirmed and not self.is_auto_confirm_enabled():
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
        secret = self._get_jwt_secret()
        payload = {
            "sub": user_id,
            "role": role,
            "exp": datetime.now(timezone.utc) + timedelta(days=7)
        }
        return jwt.encode(payload, secret, algorithm="HS256")

    def verify_jwt(self, token: str) -> dict:
        """Verify the JWT token and return the payload."""
        from jose import jwt, JWTError
        secret = self._get_jwt_secret()
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
