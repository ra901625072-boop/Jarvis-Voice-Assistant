"""
tests/unit/test_system_tools.py — Unit tests for SystemTools hardening.
"""
import os
import pytest
from unittest.mock import patch

from tools.builtin.system.tool import SystemTools


class TestSystemToolsUnit:
    @pytest.mark.asyncio
    async def test_terminal_disabled_by_default(self, security_manager):
        """Commands must be blocked when JARVIS_ENABLE_TERMINAL is false."""
        with patch.dict(os.environ, {"JARVIS_ENABLE_TERMINAL": "false"}):
            tool = SystemTools(security=security_manager)
            res = await tool.run_terminal_command(command="whoami", confirmed=True)
            assert "disabled by security policy" in res

    @pytest.mark.asyncio
    async def test_unallowlisted_commands_rejected(self, security_manager):
        """Commands not in ALLOWED_COMMANDS must be rejected."""
        with patch.dict(os.environ, {"JARVIS_ENABLE_TERMINAL": "true"}):
            tool = SystemTools(security=security_manager)
            forbidden_commands = [
                "powershell -c Get-Process",
                "curl http://attacker.com",
                "rm -rf /",
                "del /f /q C:\\*",
                "bash -i",
                "reg add HKLM\\Software"
            ]
            for cmd in forbidden_commands:
                res = await tool.run_terminal_command(command=cmd, confirmed=True)
                assert "not in the approved command allowlist" in res

    @pytest.mark.asyncio
    async def test_command_chaining_and_redirection_rejected(self, security_manager):
        """Shell operators (&&, ;, |, >, <, `) must be blocked."""
        with patch.dict(os.environ, {"JARVIS_ENABLE_TERMINAL": "true"}):
            tool = SystemTools(security=security_manager)
            injection_commands = [
                "dir && whoami",
                "echo hello; tasklist",
                "dir | findstr py",
                "echo test > output.txt",
                "whoami`whoami`",
                "echo $SECRET"
            ]
            for cmd in injection_commands:
                res = await tool.run_terminal_command(command=cmd, confirmed=True)
                assert "Command chaining" in res

    @pytest.mark.asyncio
    async def test_confirmation_required_for_terminal(self, security_manager):
        """Unconfirmed commands must return confirmation requirement warning."""
        with patch.dict(os.environ, {"JARVIS_ENABLE_TERMINAL": "true"}):
            tool = SystemTools(security=security_manager)
            res = await tool.run_terminal_command(command="echo Hello", confirmed=False)
            assert "SECURITY WARNING" in res or "CONFIRMATION_REQUIRED" in res or "requires confirmation" in res.lower()
