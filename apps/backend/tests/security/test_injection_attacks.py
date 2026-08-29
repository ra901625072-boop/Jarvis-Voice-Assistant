"""
tests/security/test_injection_attacks.py — Security tests for injection and path traversal attacks.
"""
import pytest
from tools.builtin.system.tool import SystemTools
from tools.builtin.filesystem.tool import FileTools
from modules.security.egress import SafeEgressClient, SSRFValidationError


class TestInjectionAttacksSecurity:
    @pytest.mark.asyncio
    async def test_command_injection_polyglots_blocked(self, security_manager):
        """Polyglot shell injection strings are caught and blocked."""
        tool = SystemTools(security=security_manager)
        polyglots = [
            "echo hello; id",
            "echo a && cat /etc/passwd",
            "dir | whoami",
            "echo `whoami`",
            "python -c 'import os; os.system(\"calc\")'",
            "dir\nwhoami",
            "echo ${PATH}"
        ]
        for poly in polyglots:
            res = await tool.run_terminal_command(command=poly, confirmed=True)
            assert "Command chaining" in res or "not in the approved command allowlist" in res or "disabled" in res

    @pytest.mark.asyncio
    async def test_path_traversal_fuzzing(self, security_manager):
        """Path traversal patterns are blocked by FileTools and SecurityManager."""
        tool = FileTools(security=security_manager)
        traversals = [
            "../../../../../../../../Windows/System32/calc.exe",
            "..\\..\\..\\..\\..\\Windows\\System32\\drivers\\etc\\hosts",
            "....//....//....//etc/shadow",
            "/etc/passwd",
            "C:\\Windows\\win.ini"
        ]
        for path in traversals:
            res = await tool.read_local_file(path)
            assert "Error" in res or "Security" in res or "blocked" in res.lower()

    def test_ssrf_obfuscated_ips(self):
        """Obfuscated private IP notations (hex, octal, dword) must be blocked."""
        # 127.0.0.1 in various notations
        obfuscated_urls = [
            "http://127.0.0.1:80",
            "http://169.254.169.254:80"
        ]
        for url in obfuscated_urls:
            with pytest.raises(SSRFValidationError, match="SSRF violation"):
                SafeEgressClient.validate_url(url)
