import os
import pytest
from fastapi.testclient import TestClient

# Set up dummy environment variables for tests
os.environ["JARVIS_API_KEY"] = "test_secret_key"
os.environ["LIVEKIT_URL"] = "ws://localhost:7880"
os.environ["LIVEKIT_API_KEY"] = "lk_key"
os.environ["LIVEKIT_API_SECRET"] = "lk_secret"

from api.app import app

client = TestClient(app)

def test_token_auth_invalid():
    response = client.post("/api/auth/token", json={"api_key": "wrong_key"})
    assert response.status_code == 401
    assert "detail" in response.json()

def test_token_auth_valid():
    key = os.environ.get("JARVIS_API_KEY", "test_secret_key")
    response = client.post("/api/auth/token", json={"api_key": key})
    assert response.status_code == 200
    data = response.json()
    assert "token" in data

def test_get_stats_unauthorized():
    response = client.get("/api/stats")
    # Missing authorization header
    assert response.status_code == 401

def test_get_stats_authorized():
    # Login first
    key = os.environ.get("JARVIS_API_KEY", "test_secret_key")
    login_res = client.post("/api/auth/token", json={"api_key": key})
    token = login_res.json()["token"]
    
    response = client.get(
        "/api/stats",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "cpu" in data
    assert "temp" in data

def test_list_tasks_authorized():
    key = os.environ.get("JARVIS_API_KEY", "test_secret_key")
    login_res = client.post("/api/auth/token", json={"api_key": key})
    token = login_res.json()["token"]
    
    response = client.get(
        "/api/tasks",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "tasks" in data

def test_list_agents_authorized():
    key = os.environ.get("JARVIS_API_KEY", "test_secret_key")
    login_res = client.post("/api/auth/token", json={"api_key": key})
    token = login_res.json()["token"]
    
    response = client.get(
        "/api/agents",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "agents" in data
