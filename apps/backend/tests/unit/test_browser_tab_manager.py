"""
tests/unit/test_browser_tab_manager.py — Unit Tests for Tab Manager, Ownership, and Server Tab Protection.
"""

import pytest
from unittest.mock import MagicMock
from modules.browser.tab_manager import TabManager, TabRecord


class TestBrowserTabManager:
    def test_is_server_url_detection(self):
        # Protected URLs
        assert TabManager.is_server_url("http://localhost:8000") is True
        assert TabManager.is_server_url("http://localhost:8000/dashboard") is True
        assert TabManager.is_server_url("http://127.0.0.1:8000") is True
        assert TabManager.is_server_url("http://192.168.1.50:8000/api") is True
        
        # Unprotected external URLs
        assert TabManager.is_server_url("https://www.google.com") is False
        assert TabManager.is_server_url("https://en.wikipedia.org/wiki/Black_hole") is False
        assert TabManager.is_server_url("http://localhost:3000") is False
        assert TabManager.is_server_url("") is False
        assert TabManager.is_server_url(None) is False

    def test_register_and_retrieve_tab(self):
        manager = TabManager()
        mock_page = MagicMock()
        mock_page.url = "https://www.google.com"

        record = manager.register_tab(
            page=mock_page,
            owner="agent:task_123",
            parent_task_id="task_123",
        )

        assert record.tab_id.startswith("tab_")
        assert record.owner == "agent:task_123"
        assert record.protected is False
        assert record.parent_task_id == "task_123"

        # Lookup by Page
        retrieved = manager.get_tab(mock_page)
        assert retrieved is not None
        assert retrieved.tab_id == record.tab_id

        # Lookup by tab_id
        assert manager.get_tab(record.tab_id) == record

    def test_auto_protect_server_tabs(self):
        manager = TabManager()
        server_page = MagicMock()
        server_page.url = "http://localhost:8000"

        record = manager.register_tab(page=server_page, owner="system")
        assert record.protected is True
        assert manager.is_protected(server_page) is True
        assert manager.is_protected(record.tab_id) is True

    def test_tab_ownership_verification(self):
        record = TabRecord(
            tab_id="tab_test",
            page_ref=MagicMock(),
            owner="agent:task_99",
            parent_task_id="task_99",
        )

        assert record.is_owned_by("task_99") is True
        assert record.is_owned_by("agent:task_99") is True
        assert record.is_owned_by("task_other") is False
        assert record.is_owned_by(None) is False

    def test_unregister_tab(self):
        manager = TabManager()
        mock_page = MagicMock()
        mock_page.url = "https://example.com"

        record = manager.register_tab(mock_page, owner="agent:task_1")
        assert manager.get_tab(record.tab_id) is not None

        unregistered = manager.unregister_tab(record.tab_id)
        assert unregistered is not None
        assert unregistered.tab_id == record.tab_id
        assert manager.get_tab(record.tab_id) is None
        assert manager.get_tab(mock_page) is None
