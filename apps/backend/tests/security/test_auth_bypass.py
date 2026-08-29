"""
tests/security/test_auth_bypass.py — Security tests for authentication bypass & JWT attacks.
"""
import pytest
from jose import jwt
from datetime import datetime, timedelta, timezone


class TestAuthBypassSecurity:
    def test_forged_jwt_signature_rejected(self, api_client):
        """Tokens signed with a different key must be rejected with 401."""
        payload = {
            "sub": "attacker",
            "role": "admin",
            "exp": datetime.now(timezone.utc) + timedelta(days=1)
        }
        attacker_token = jwt.encode(payload, "completely_different_attacker_secret_key_32b", algorithm="HS256")
        
        response = api_client.get("/api/workflows", headers={"Authorization": f"Bearer {attacker_token}"})
        assert response.status_code == 401

    def test_expired_jwt_rejected(self, api_client, security_manager):
        """Expired JWT tokens must be rejected with 401."""
        secret = security_manager._get_jwt_secret()
        expired_payload = {
            "sub": "user1",
            "role": "admin",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1)
        }
        expired_token = jwt.encode(expired_payload, secret, algorithm="HS256")

        response = api_client.get("/api/workflows", headers={"Authorization": f"Bearer {expired_token}"})
        assert response.status_code == 401

    def test_algorithm_none_rejected(self, api_client):
        """Tokens with alg: none must be rejected."""
        token_none = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJhZG1pbiIsInJvbGUiOiJhZG1pbiJ9."
        response = api_client.get("/api/workflows", headers={"Authorization": f"Bearer {token_none}"})
        assert response.status_code == 401

    def test_missing_bearer_prefix_rejected(self, api_client, security_manager):
        """Token passed without Bearer prefix must be rejected with 401."""
        valid_token = security_manager.create_jwt(user_id="user1", role="admin")
        response = api_client.get("/api/workflows", headers={"Authorization": valid_token})
        assert response.status_code == 401
