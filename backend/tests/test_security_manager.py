import pytest
import sys
import os

# Adjust sys.path to run tests from backend folder root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.core.security_manager import SecurityManager

def test_security_manager_policy_tiers():
    sm = SecurityManager()
    
    # Verify standard TIER_SAFE categories
    assert sm.get_tier("open") == SecurityManager.TIER_SAFE
    assert sm.get_tier("read") == SecurityManager.TIER_SAFE
    
    # Verify TIER_CONFIRM categories
    assert sm.get_tier("delete") == SecurityManager.TIER_CONFIRM
    assert sm.get_tier("power") == SecurityManager.TIER_CONFIRM
    assert sm.get_tier("shell") == SecurityManager.TIER_CONFIRM
    assert sm.get_tier("install") == SecurityManager.TIER_CONFIRM
    assert sm.get_tier("move") == SecurityManager.TIER_CONFIRM
    assert sm.get_tier("rename") == SecurityManager.TIER_CONFIRM
    assert sm.get_tier("close_app") == SecurityManager.TIER_CONFIRM
    
    # Verify TIER_FORBIDDEN categories
    assert sm.get_tier("registry") == SecurityManager.TIER_FORBIDDEN
    assert sm.get_tier("security_bypass") == SecurityManager.TIER_FORBIDDEN

def test_security_manager_fail_closed():
    sm = SecurityManager()
    # Any unknown/arbitrary category should default to TIER_CONFIRM (fail-closed)
    assert sm.get_tier("unknown_scary_category") == SecurityManager.TIER_CONFIRM
    assert sm.requires_confirmation("unknown_scary_category", "do_something") is True

def test_security_manager_forbidden_raises_permission_error():
    sm = SecurityManager()
    with pytest.raises(PermissionError):
        sm.requires_confirmation("registry", "edit_registry")

def test_security_manager_pre_flight_check():
    sm = SecurityManager()
    # Critical directory block
    assert sm.pre_flight_check("delete", "C:\\Windows\\System32\\cmd.exe") is False
    # Safe path passes
    assert sm.pre_flight_check("delete", "D:\\Jarvis\\my_file.txt") is True
