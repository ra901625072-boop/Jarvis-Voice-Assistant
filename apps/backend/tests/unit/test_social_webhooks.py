import os
import json
import sqlite3
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from api.app import create_fastapi_app
from ai.agents.types import AgentTask, AgentResult

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "contacts.db"))


@pytest.fixture
def client():
    # Setup test token environment
    os.environ["META_VERIFY_TOKEN"] = "test_verification_token"
    app = create_fastapi_app()
    return TestClient(app)


def test_whatsapp_webhook_verification(client):
    # Test successful verification
    resp = client.get(
        "/api/social/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=test_verification_token&hub.challenge=12345"
    )
    assert resp.status_code == 200
    assert resp.text == "12345"

    # Test unsuccessful verification
    resp = client.get(
        "/api/social/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=invalid_token&hub.challenge=12345"
    )
    assert resp.status_code == 403


def test_instagram_webhook_verification(client):
    # Test successful verification
    resp = client.get(
        "/api/social/webhook/instagram?hub.mode=subscribe&hub.verify_token=test_verification_token&hub.challenge=abcde"
    )
    assert resp.status_code == 200
    assert resp.text == "abcde"


def test_whatsapp_webhook_inbound_caching(client):
    # Prepare WhatsApp message webhook payload
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1234567890",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550000000",
                                "phone_number_id": "987654321"
                            },
                            "messages": [
                                {
                                    "from": "19998887777",
                                    "id": "wamid.HBgLMTk5OTg4ODc3NzdGAhIAEhg0",
                                    "timestamp": "1724777000",
                                    "type": "text",
                                    "text": {
                                        "body": "Hello from pytest"
                                    }
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

    # Post webhook
    resp = client.post("/api/social/webhook/whatsapp", json=payload)
    assert resp.status_code == 200

    # Query SQLite database to verify cache insert
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM social_inbound_messages WHERE platform='whatsapp' AND sender='19998887777'")
        row = cursor.fetchone()
        assert row is not None
        assert row["text"] == "Hello from pytest"
        assert row["message_id"] == "wamid.HBgLMTk5OTg4ODc3NzdGAhIAEhg0"


def test_pending_approvals_endpoints(client, auth_headers):
    # Insert a dummy pending task into the database
    import uuid
    from datetime import datetime

    task_id = str(uuid.uuid4())
    payload = {"to": "1234567890", "body": "Hello Pytest Approve"}

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_approvals (
                id TEXT PRIMARY KEY,
                platform TEXT,
                task_type TEXT,
                payload TEXT,
                correlation_id TEXT,
                timestamp TEXT,
                status TEXT
            )
        """)
        conn.execute("""
            INSERT OR REPLACE INTO pending_approvals (id, platform, task_type, payload, correlation_id, timestamp, status)
            VALUES (?, 'whatsapp', 'send_message', ?, 'test-corr', ?, 'PENDING')
        """, (task_id, json.dumps(payload), datetime.now().isoformat()))

    mock_agent = MagicMock()
    async def fake_handle(task):
        return AgentResult(
            task_id="result-task-id",
            success=True,
            result={"status": "sent", "message_id": "meta-msg-id"}
        )
    mock_agent.handle = fake_handle

    mock_container = MagicMock()
    mock_container.get.return_value = MagicMock()
    mock_container.get_or_none.return_value = mock_agent

    with patch("container.ServiceContainer.instance", return_value=mock_container):
        # 1. Test GET approvals lists it
        resp = client.get("/api/social/approvals", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json().get("pending_approvals", [])
        assert any(item["id"] == task_id for item in data)

        # 2. Test POST approve executes it (mocking agent)
        resp = client.post(f"/api/social/approve/{task_id}", headers=auth_headers)
        assert resp.status_code == 200
        res_data = resp.json()
        assert res_data["status"] == "success"
        assert res_data["result"]["message_id"] == "meta-msg-id"

        # 3. Test POST reject updates status to REJECTED
        task_id_reject = str(uuid.uuid4())
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO pending_approvals (id, platform, task_type, payload, correlation_id, timestamp, status)
                VALUES (?, 'whatsapp', 'send_message', ?, 'test-corr', ?, 'PENDING')
            """, (task_id_reject, json.dumps(payload), datetime.now().isoformat()))

        resp = client.post(f"/api/social/reject/{task_id_reject}", headers=auth_headers)
        assert resp.status_code == 200

    # Verify status updated to APPROVED and REJECTED in DB
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM pending_approvals WHERE id = ?", (task_id,))
        assert cursor.fetchone()[0] == "APPROVED"
        cursor.execute("SELECT status FROM pending_approvals WHERE id = ?", (task_id_reject,))
        assert cursor.fetchone()[0] == "REJECTED"
