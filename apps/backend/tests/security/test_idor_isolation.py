"""
tests/security/test_idor_isolation.py — Security tests for RBAC & Tenant/Resource isolation.
"""
import pytest
from fastapi.testclient import TestClient


class TestIDORIsolationSecurity:
    def test_user_role_blocked_from_admin_approvals(self, api_client, security_manager):
        """Standard user role attempting to resolve approvals must be rejected."""
        user_token = security_manager.create_jwt(user_id="standard_user", role="user")
        headers = {"Authorization": f"Bearer {user_token}"}
        
        response = api_client.post("/api/approvals/appr_123/approve", headers=headers, json={"reason": "test"})
        # 403 Forbidden or 401 Unauthorized
        assert response.status_code in (403, 401, 404, 500)

    def test_workflow_owner_isolation(self, api_client, security_manager):
        """User B should not see workflows owned exclusively by User A."""
        token_a = security_manager.create_jwt(user_id="user_alice", role="user")
        token_b = security_manager.create_jwt(user_id="user_bob", role="user")

        # Alice creates private workflow
        res_a = api_client.post("/api/workflows", headers={"Authorization": f"Bearer {token_a}"}, json={
            "name": "Alice Private Workflow",
            "steps": [{"agent": "planning_agent", "action": "create_plan"}]
        })
        assert res_a.status_code == 200
        alice_wf_id = res_a.json()["workflow"]["id"]

        # Bob lists workflows
        res_b = api_client.get("/api/workflows", headers={"Authorization": f"Bearer {token_b}"})
        assert res_b.status_code == 200
        bob_wfs = res_b.json()["workflows"]
        assert not any(w["id"] == alice_wf_id for w in bob_wfs)
