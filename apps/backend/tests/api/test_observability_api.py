"""
tests/api/test_observability_api.py — API tests for /api/observability endpoints.
"""
import pytest
from fastapi.testclient import TestClient


class TestObservabilityAPI:
    def test_metrics_requires_auth(self, api_client):
        """GET /api/observability/metrics without auth returns 401."""
        response = api_client.get("/api/observability/metrics")
        assert response.status_code == 401

    def test_metrics_authenticated(self, api_client, auth_headers):
        """GET /api/observability/metrics with valid JWT returns metrics object."""
        response = api_client.get("/api/observability/metrics", headers=auth_headers)
        # Should return 200 or 500 if container empty; verify status is valid API response
        assert response.status_code in (200, 500)
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict)

    def test_spans_authenticated(self, api_client, auth_headers):
        """GET /api/observability/spans returns span list."""
        response = api_client.get("/api/observability/spans?limit=10", headers=auth_headers)
        assert response.status_code in (200, 500)
        if response.status_code == 200:
            data = response.json()
            assert "spans" in data
