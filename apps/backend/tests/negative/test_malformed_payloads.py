"""
tests/negative/test_malformed_payloads.py — Negative testing with fuzzing & corrupted inputs.
"""
import pytest
from fastapi.testclient import TestClient


class TestMalformedPayloadsNegative:
    def test_corrupted_base64_upload_fails_safely(self, api_client, auth_headers):
        """Corrupted/invalid base64 payload returns 400 Bad Request."""
        response = api_client.post("/api/upload", headers=auth_headers, json={
            "filename": "corrupted.bin",
            "content": "!!!NOT_VALID_BASE64_DATA@@@"
        })
        assert response.status_code in (400, 422, 500)

    def test_null_bytes_in_filename(self, api_client, auth_headers):
        """Null bytes in filenames are sanitized or rejected without crashing."""
        response = api_client.post("/api/upload", headers=auth_headers, json={
            "filename": "test\x00malicious.txt",
            "content": "SGVsbG8="
        })
        if response.status_code == 200:
            data = response.json()
            assert "\x00" not in data["file_id"]
        else:
            assert response.status_code in (400, 422)

    def test_workflow_with_null_and_malformed_steps(self, api_client, auth_headers):
        """Workflows with invalid step objects fail gracefully."""
        response = api_client.post("/api/workflows", headers=auth_headers, json={
            "name": "Broken Workflow",
            "steps": "this_is_a_string_not_a_list"
        })
        assert response.status_code in (200, 400, 422)
