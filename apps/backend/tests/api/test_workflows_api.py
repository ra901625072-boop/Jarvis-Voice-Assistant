"""
tests/api/test_workflows_api.py — API tests for /api/workflows endpoint.
"""
import pytest
from fastapi.testclient import TestClient


class TestWorkflowsAPI:
    def test_list_workflows_requires_auth(self, api_client):
        """GET /api/workflows without auth header returns 401."""
        response = api_client.get("/api/workflows")
        assert response.status_code == 401

    def test_create_and_list_workflow(self, api_client, auth_headers):
        """POST /api/workflows creates workflow; GET /api/workflows lists it."""
        payload = {
            "name": "Automated Security Audit",
            "steps": [
                {"agent": "planning_agent", "action": "create_plan", "payload": {}},
                {"agent": "verification_agent", "action": "verify_result", "payload": {}}
            ]
        }
        res_create = api_client.post("/api/workflows", headers=auth_headers, json=payload)
        assert res_create.status_code == 200
        created = res_create.json()
        assert "workflow" in created
        wf_id = created["workflow"]["id"]

        # List workflows
        res_list = api_client.get("/api/workflows", headers=auth_headers)
        assert res_list.status_code == 200
        wfs = res_list.json()["workflows"]
        assert any(w["id"] == wf_id for w in wfs)

    def test_create_workflow_missing_name(self, api_client, auth_headers):
        """POST /api/workflows without name returns 400."""
        response = api_client.post("/api/workflows", headers=auth_headers, json={"steps": []})
        assert response.status_code in (400, 422)
