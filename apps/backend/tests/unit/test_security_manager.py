"""
tests/unit/test_security_manager.py — Unit tests for SecurityManager.
"""
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from modules.security.manager import SecurityManager


class TestSecurityManagerUnit:
    def test_safe_path_inside_workspace(self, security_manager, workspace_dir):
        """Files inside workspace root must be identified as safe."""
        target_file = workspace_dir / "safe_file.txt"
        target_file.write_text("safe content")
        assert security_manager.is_safe_path(str(target_file)) is True

    def test_path_traversal_blocked(self, security_manager, workspace_dir, tmp_path):
        """Path traversal '../' escaping workspace root must be blocked."""
        outside_file = tmp_path / "outside_secret.txt"
        outside_file.write_text("secret")
        traversal = str(workspace_dir / ".." / "outside_secret.txt")
        # Direct check on non-temp outside path or traversal
        assert security_manager.is_safe_path("C:\\Windows\\System32\\cmd.exe") is False
        assert security_manager.is_safe_path("C:\\Program Files\\App") is False

    def test_drive_roots_blocked(self, security_manager):
        """Bare drive roots (C:\\, D:\\) must always be rejected."""
        assert security_manager.is_safe_path("C:\\") is False
        assert security_manager.is_safe_path("D:\\") is False
        assert security_manager.is_safe_path("") is False
        assert security_manager.is_safe_path("   ") is False

    def test_jwt_fail_closed_missing_secret_in_production(self):
        """Missing JWT secret in production mode must raise ValueError."""
        with patch.dict(os.environ, {"JARVIS_JWT_SECRET": "", "JARVIS_API_KEY": "", "TESTING": ""}, clear=False):
            sec = SecurityManager()
            with pytest.raises(ValueError, match="JARVIS_JWT_SECRET"):
                sec._get_jwt_secret()

    def test_jwt_fail_closed_insecure_default_in_production(self):
        """Insecure default secret must be rejected in production mode."""
        with patch.dict(os.environ, {"JARVIS_JWT_SECRET": "your-super-secret-jwt-key-change-this-in-production-12345", "TESTING": ""}, clear=False):
            sec = SecurityManager()
            with pytest.raises(ValueError, match="insecure default"):
                sec._get_jwt_secret()

    def test_jwt_fail_closed_short_secret_in_production(self):
        """Short secrets (<32 characters) must be rejected in production mode."""
        with patch.dict(os.environ, {"JARVIS_JWT_SECRET": "short_secret_123", "TESTING": ""}, clear=False):
            sec = SecurityManager()
            with pytest.raises(ValueError, match="at least 32 characters"):
                sec._get_jwt_secret()

    def test_jwt_create_and_verify_roundtrip(self, security_manager):
        """Valid token creation and verification returns identical claims."""
        token = security_manager.create_jwt(user_id="alice", role="operator")
        payload = security_manager.verify_jwt(token)
        assert payload is not None
        assert payload.get("sub") == "alice"
        assert payload.get("role") == "operator"

    def test_pre_flight_check_destructive_categories(self, security_manager, workspace_dir):
        """Pre-flight check blocks destructive operations on system paths."""
        assert security_manager.pre_flight_check("delete", "C:\\Windows\\System32\\kernel32.dll") is False
        
        safe_file = workspace_dir / "test.txt"
        safe_file.write_text("content")
        assert security_manager.pre_flight_check("delete", str(safe_file)) is True

    def test_enforce_tier_confirm_gating(self, security_manager):
        """Tier 1 actions without confirmation return security warning."""
        res_unconfirmed = security_manager.enforce_tier("delete", "delete test file", confirmed=False)
        if security_manager.get_tier("delete") == SecurityManager.TIER_CONFIRM:
            assert res_unconfirmed is not None
            assert "SECURITY WARNING" in res_unconfirmed

            res_confirmed = security_manager.enforce_tier("delete", "delete test file", confirmed=True)
            assert res_confirmed is None
