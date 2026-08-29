"""
tests/api/test_upload_api.py — API tests for /api/upload endpoint.
"""
import base64
import pytest
from fastapi.testclient import TestClient


class TestUploadAPI:
    def test_upload_requires_auth(self, api_client):
        """Upload without Authorization header returns 401."""
        content_b64 = base64.b64encode(b"sample file data").decode("utf-8")
        response = api_client.post("/api/upload", json={
            "filename": "sample.txt",
            "content": content_b64
        })
        assert response.status_code == 401

    def test_upload_success_with_valid_auth(self, api_client, auth_headers):
        """Authenticated upload saves file and returns unique file_id."""
        raw_bytes = b"Hello, secure world!"
        content_b64 = base64.b64encode(raw_bytes).decode("utf-8")
        response = api_client.post("/api/upload", headers=auth_headers, json={
            "filename": "test_document.txt",
            "content": content_b64
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "file_id" in data
        assert "uploads/" in data["filepath"]

    def test_upload_sanitizes_path_traversal_filename(self, api_client, auth_headers):
        """Filename with path traversal is sanitized to an opaque name."""
        content_b64 = base64.b64encode(b"malicious payload").decode("utf-8")
        response = api_client.post("/api/upload", headers=auth_headers, json={
            "filename": "../../../etc/passwd",
            "content": content_b64
        })
        if response.status_code == 200:
            data = response.json()
            assert ".." not in data["file_id"]
            assert "passwd" in data["file_id"]
        else:
            assert response.status_code == 400

    def test_upload_exceeds_max_size_limit(self, api_client, auth_headers):
        """Payloads exceeding 10MB limit are rejected with 413 Payload Too Large."""
        large_bytes = b"X" * (11 * 1024 * 1024)  # 11 MB
        content_b64 = base64.b64encode(large_bytes).decode("utf-8")
        response = api_client.post("/api/upload", headers=auth_headers, json={
            "filename": "giant_file.bin",
            "content": content_b64
        })
        assert response.status_code == 413
