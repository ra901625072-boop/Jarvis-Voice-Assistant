"""
tests/security/test_rate_limiting.py — Security tests for API rate limiting.
"""
import pytest
from fastapi.testclient import TestClient


class TestRateLimitingSecurity:
    def test_brute_force_login_blocked(self, api_client):
        """Repeated failed login attempts trigger 429 rate limit."""
        blocked = False
        for _ in range(10):
            res = api_client.post("/api/auth/token", json={"api_key": "brute_force_guess"})
            if res.status_code == 429:
                blocked = True
                break
        assert blocked is True
