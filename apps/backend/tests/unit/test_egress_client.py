"""
tests/unit/test_egress_client.py — Unit tests for SafeEgressClient SSRF protection.
"""
import pytest
from unittest.mock import patch, MagicMock
from modules.security.egress import SafeEgressClient, SSRFValidationError


class TestEgressClientUnit:
    def test_loopback_ip_blocked(self):
        """Outbound connection to localhost/127.0.0.1 must be blocked."""
        with pytest.raises(SSRFValidationError, match="SSRF violation"):
            SafeEgressClient.validate_url("http://127.0.0.1:8000/admin")

    def test_cloud_metadata_blocked(self):
        """Outbound connection to 169.254.169.254 must be blocked."""
        with pytest.raises(SSRFValidationError, match="SSRF violation"):
            SafeEgressClient.validate_url("http://169.254.169.254/latest/meta-data/")

    def test_private_rfc1918_ips_blocked(self):
        """Outbound connections to 10.x, 172.16.x, and 192.168.x must be blocked."""
        for ip in ["10.0.0.1", "172.16.0.5", "192.168.1.100"]:
            with pytest.raises(SSRFValidationError, match="SSRF violation"):
                SafeEgressClient.validate_url(f"http://{ip}/internal")

    def test_unsupported_schemes_blocked(self):
        """Schemes other than http/https must be rejected."""
        unsupported = [
            "file:///etc/passwd",
            "gopher://example.com",
            "ftp://ftp.example.com",
            "javascript:alert(1)"
        ]
        for url in unsupported:
            with pytest.raises(SSRFValidationError, match="not permitted|Invalid URL"):
                SafeEgressClient.validate_url(url)

    def test_valid_public_domain_allowed(self):
        """Valid public URLs with valid DNS should pass validation."""
        # Use a well-known public hostname (e.g. google.com or example.com)
        validated = SafeEgressClient.validate_url("https://example.com")
        assert validated == "https://example.com"
