"""
tests/unit/test_flask_app.py — Unit tests for the Flask web server.

Phase 5: Tests for require_api_key decorator, rate limiter, and token endpoint.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    Create a Flask test client with required environment variables mocked.
    """
    import importlib

    monkeypatch.setenv("JARVIS_API_KEY", "test-api-key-12345")
    monkeypatch.setenv("LIVEKIT_URL", "ws://localhost:7880")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-lk-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-lk-secret")

    # Create a dummy frontend folder
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html>JARVIS</html>")

    from server.flask_app import create_app
    app = create_app(str(frontend))
    app.config["TESTING"] = True

    with app.test_client() as c:
        yield c


class TestRequireApiKey:
    def test_missing_auth_header_returns_401(self, client):
        response = client.get("/stats")
        assert response.status_code == 401

    def test_wrong_auth_header_returns_401(self, client):
        response = client.get("/stats", headers={"Authorization": "wrong-key"})
        assert response.status_code == 401

    def test_correct_auth_header_returns_200(self, client):
        response = client.get("/stats", headers={"Authorization": "test-api-key-12345"})
        assert response.status_code == 200

    def test_auth_in_query_param_blocked(self, client):
        """API key must be in Authorization header only — not query string."""
        response = client.get("/stats?key=test-api-key-12345")
        assert response.status_code == 401


class TestStatsEndpoint:
    def test_stats_returns_cpu_field(self, client):
        response = client.get("/stats", headers={"Authorization": "test-api-key-12345"})
        data = response.get_json()
        assert "cpu" in data
        assert isinstance(data["cpu"], (int, float))

    def test_stats_returns_temp_field(self, client):
        response = client.get("/stats", headers={"Authorization": "test-api-key-12345"})
        data = response.get_json()
        assert "temp" in data

    def test_stats_returns_temp_source_field(self, client):
        response = client.get("/stats", headers={"Authorization": "test-api-key-12345"})
        data = response.get_json()
        assert "temp_source" in data


class TestIndexEndpoint:
    def test_index_serves_html(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"JARVIS" in response.data


class TestRateLimiter:
    def test_rate_limit_allows_5_requests(self, client):
        """First 5 token requests from same IP should succeed."""
        for _ in range(5):
            response = client.get(
                "/token",
                headers={"Authorization": "test-api-key-12345"},
                environ_base={"REMOTE_ADDR": "10.0.0.1"},
            )
            # May return 200 or 500 (if LiveKit dispatch fails in test env)
            assert response.status_code != 429

    def test_rate_limit_blocks_6th_request(self, client):
        """6th token request from same IP within 60s should be rate-limited."""
        for _ in range(5):
            client.get(
                "/token",
                headers={"Authorization": "test-api-key-12345"},
                environ_base={"REMOTE_ADDR": "10.0.0.2"},
            )
        response = client.get(
            "/token",
            headers={"Authorization": "test-api-key-12345"},
            environ_base={"REMOTE_ADDR": "10.0.0.2"},
        )
        assert response.status_code == 429
