"""
tests/api/test_tasks_api.py — API tests for /api/tasks endpoint.
"""
import pytest
from fastapi.testclient import TestClient


class TestTasksAPI:
    def test_list_tasks_requires_auth(self, api_client):
        """GET /api/tasks without authorization token returns 401."""
        response = api_client.get("/api/tasks")
        assert response.status_code == 401

    def test_list_tasks_authenticated(self, api_client, auth_headers):
        """GET /api/tasks with valid JWT returns task list structure."""
        response = api_client.get("/api/tasks", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
        assert isinstance(data["tasks"], list)

    def test_get_nonexistent_task(self, api_client, auth_headers):
        """GET /api/tasks/{task_id} for nonexistent task returns 404."""
        response = api_client.get("/api/tasks/non_existent_task_id_12345", headers=auth_headers)
        assert response.status_code == 404

    def test_create_task_missing_input(self, api_client, auth_headers):
        """POST /api/tasks without input string returns 400."""
        response = api_client.post("/api/tasks", headers=auth_headers, json={})
        assert response.status_code in (400, 422)
