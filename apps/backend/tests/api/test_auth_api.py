"""
tests/api/test_auth_api.py — API tests for /api/auth/token endpoint.
"""
import os
import pytest
from fastapi.testclient import TestClient


class TestAuthAPI:
    def test_login_success(self, api_client):
        """Valid API key issues signed JWT token."""
        api_key = os.environ.get("JARVIS_API_KEY", "test_super_secret_api_key_for_testing_purposes")
        response = api_client.post("/api/auth/token", json={"api_key": api_key})
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data.get("token_type") == "bearer"

    def test_login_invalid_key(self, api_client):
        """Invalid API key returns 401 Unauthorized."""
        response = api_client.post("/api/auth/token", json={"api_key": "wrong_key_12345"})
        assert response.status_code == 401

    def test_login_missing_key(self, api_client):
        """Missing API key field fails schema validation or returns 401/422."""
        response = api_client.post("/api/auth/token", json={})
        assert response.status_code in (401, 422)

    def test_auth_rate_limiting(self, api_client):
        """Exceeding 5 token requests per minute triggers 429 Too Many Requests."""
        api_key = os.environ.get("JARVIS_API_KEY", "test_super_secret_api_key_for_testing_purposes")
        statuses = []
        for _ in range(7):
            res = api_client.post("/api/auth/token", json={"api_key": api_key})
            statuses.append(res.status_code)
        
        assert 429 in statuses
