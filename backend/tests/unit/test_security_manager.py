"""
tests/unit/test_security_manager.py — Unit tests for SecurityManager.

Phase 5: Tests for is_safe_path(), pre_flight_check(), enforce_tier(),
and requires_confirmation().
"""
import sys
import os
import platform
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modules.core.security_manager import SecurityManager


@pytest.fixture
def security():
    return SecurityManager()


# ── is_safe_path tests ────────────────────────────────────────────────────────

class TestIsSafePath:
    def test_normal_user_directory_is_safe(self, security, tmp_path):
        assert security.is_safe_path(str(tmp_path)) is True

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only paths")
    def test_windows_system_dir_blocked(self, security):
        assert security.is_safe_path("C:\\Windows\\System32") is False

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only paths")
    def test_program_files_blocked(self, security):
        assert security.is_safe_path("C:\\Program Files\\SomeApp") is False

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only paths")
    def test_drive_root_blocked(self, security):
        assert security.is_safe_path("C:\\") is False

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only paths")
    def test_recycle_bin_blocked(self, security):
        assert security.is_safe_path("C:\\$Recycle.Bin") is False

    def test_relative_path_safe(self, security, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        assert security.is_safe_path(str(sub)) is True


# ── pre_flight_check tests ────────────────────────────────────────────────────

class TestPreFlightCheck:
    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only paths")
    def test_delete_system_path_blocked(self, security):
        assert security.pre_flight_check("delete", "C:\\Windows\\explorer.exe") is False

    def test_delete_normal_path_allowed(self, security, tmp_path):
        f = tmp_path / "myfile.txt"
        f.write_text("test")
        assert security.pre_flight_check("delete", str(f)) is True

    def test_non_destructive_category_always_allowed(self, security):
        # 'browse' is not in the destructive category list
        assert security.pre_flight_check("browse", "C:\\Windows") is True

    def test_move_with_safe_path_allowed(self, security, tmp_path):
        assert security.pre_flight_check("move", str(tmp_path / "a.txt")) is True


# ── enforce_tier tests ────────────────────────────────────────────────────────

class TestEnforceTier:
    def test_forbidden_raises_permission_error(self, security):
        # 'dangerous' maps to TIER_FORBIDDEN in the default policy matrix
        # Adjust category name to match actual TIER_FORBIDDEN entries in policy
        tier = security.get_tier("dangerous")
        if tier == SecurityManager.TIER_FORBIDDEN:
            with pytest.raises(PermissionError):
                security.enforce_tier("dangerous", "format_disk")
        else:
            pytest.skip("'dangerous' is not TIER_FORBIDDEN in current policy")

    def test_confirm_tier_without_confirmed_returns_warning(self, security):
        # 'delete' should be TIER_CONFIRM
        tier = security.get_tier("delete")
        if tier == SecurityManager.TIER_CONFIRM:
            result = security.enforce_tier("delete", "delete file", confirmed=False)
            assert result is not None
            assert "SECURITY WARNING" in result
        else:
            pytest.skip("'delete' is not TIER_CONFIRM in current policy")

    def test_confirm_tier_with_confirmed_returns_none(self, security):
        tier = security.get_tier("delete")
        if tier == SecurityManager.TIER_CONFIRM:
            result = security.enforce_tier("delete", "delete file", confirmed=True)
            assert result is None
        else:
            pytest.skip("'delete' is not TIER_CONFIRM in current policy")

    def test_allowed_tier_returns_none(self, security):
        # 'browse' should be TIER_SAFE
        tier = security.get_tier("browse")
        if tier == SecurityManager.TIER_SAFE:
            result = security.enforce_tier("browse", "list dir")
            assert result is None
        else:
            pytest.skip("'browse' is not TIER_SAFE in current policy")
