"""
modules/browser/tab_manager.py — Tab Registry, Ownership Tracking, and Lifecycle Manager for JARVIS.

Ensures strict tab ownership isolation and enforces that protected tabs (e.g., JARVIS dashboard/server)
cannot be inadvertently manipulated or destroyed by automated agent tasks.
"""

import time
import uuid
import logging
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger("JARVIS.Browser.TabManager")


@dataclass
class TabRecord:
    """Represents the ownership and lifecycle metadata of a single browser tab."""
    tab_id: str
    page_ref: Any  # Playwright Page instance
    url: str = "about:blank"
    title: str = ""
    owner: str = "system"  # "system", "user", or "agent:<task_id>"
    protected: bool = False
    parent_task_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_owned_by(self, requester_id: Optional[str]) -> bool:
        """Check if the given requester ID owns this tab."""
        if not requester_id:
            return False
        if self.owner == requester_id:
            return True
        if self.parent_task_id and self.parent_task_id == requester_id:
            return True
        if self.owner == f"agent:{requester_id}":
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tab_id": self.tab_id,
            "url": self.url,
            "title": self.title,
            "owner": self.owner,
            "protected": self.protected,
            "parent_task_id": self.parent_task_id,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "metadata": self.metadata,
        }


class TabManager:
    """
    Manages tab registration, metadata, protection flags, and ownership boundaries.
    """

    PROTECTED_HOST_PATTERNS = [
        r"^localhost:8000",
        r"^127\.0\.0\.1:8000",
        r"^0\.0\.0\.0:8000",
        r"^192\.168\.\d+\.\d+:8000",
        r"^10\.\d+\.\d+\.\d+:8000",
    ]

    def __init__(self):
        self._tabs: Dict[str, TabRecord] = {}  # tab_id -> TabRecord
        self._page_to_id: Dict[Any, str] = {}  # Page instance -> tab_id
        logger.info("TabManager initialized.")

    @classmethod
    def is_server_url(cls, url: Optional[str]) -> bool:
        """
        Determines if a URL belongs to the protected JARVIS Control Server/Dashboard.
        """
        if not url:
            return False
        url_str = str(url).strip().lower()
        try:
            parsed = urlparse(url_str)
            netloc = parsed.netloc.lower()
            if not netloc and ":" in url_str:
                netloc = url_str.split("/")[0]

            for pattern in cls.PROTECTED_HOST_PATTERNS:
                if re.search(pattern, netloc):
                    return True
                
            # Additional fallback check for raw string
            if "localhost:8000" in url_str or "127.0.0.1:8000" in url_str:
                return True
        except Exception:
            pass
        return False

    def register_tab(
        self,
        page: Any,
        owner: str = "system",
        protected: Optional[bool] = None,
        parent_task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TabRecord:
        """
        Registers a Playwright Page instance into the TabManager.
        Auto-detects protection if the URL matches the server URL pattern.
        """
        # If already registered, return existing record and update
        if page in self._page_to_id:
            tab_id = self._page_to_id[page]
            record = self._tabs[tab_id]
            try:
                record.url = page.url or record.url
            except Exception:
                pass
            if protected is not None:
                record.protected = protected or self.is_server_url(record.url)
            else:
                record.protected = record.protected or self.is_server_url(record.url)
            record.last_active_at = time.time()
            return record

        tab_id = f"tab_{uuid.uuid4().hex[:8]}"
        initial_url = "about:blank"
        initial_title = ""
        try:
            initial_url = getattr(page, "url", "about:blank") or "about:blank"
        except Exception:
            pass

        is_prot = self.is_server_url(initial_url) if protected is None else (protected or self.is_server_url(initial_url))

        record = TabRecord(
            tab_id=tab_id,
            page_ref=page,
            url=initial_url,
            title=initial_title,
            owner=owner,
            protected=is_prot,
            parent_task_id=parent_task_id,
            created_at=time.time(),
            last_active_at=time.time(),
            metadata=metadata or {},
        )

        self._tabs[tab_id] = record
        self._page_to_id[page] = tab_id
        logger.debug(f"Registered {tab_id} (owner='{owner}', protected={record.protected}, url='{initial_url}')")
        return record

    def update_tab_state(self, page: Any, url: Optional[str] = None, title: Optional[str] = None) -> Optional[TabRecord]:
        """Updates the URL and title for an active tab."""
        tab_id = self._page_to_id.get(page)
        if not tab_id or tab_id not in self._tabs:
            return None
        record = self._tabs[tab_id]
        if url is not None:
            record.url = url
            if self.is_server_url(url):
                record.protected = True
        if title is not None:
            record.title = title
        record.last_active_at = time.time()
        return record

    def unregister_tab(self, page_or_tab_id: Any) -> Optional[TabRecord]:
        """Removes a tab record upon tab closure."""
        tab_id = None
        if isinstance(page_or_tab_id, str):
            tab_id = page_or_tab_id
        else:
            tab_id = self._page_to_id.get(page_or_tab_id)

        if not tab_id or tab_id not in self._tabs:
            return None

        record = self._tabs.pop(tab_id)
        if record.page_ref in self._page_to_id:
            del self._page_to_id[record.page_ref]

        logger.debug(f"Unregistered {tab_id} (owner='{record.owner}')")
        return record

    def get_tab(self, page_or_tab_id: Any) -> Optional[TabRecord]:
        """Retrieves a TabRecord by tab_id or Page reference."""
        if isinstance(page_or_tab_id, str):
            return self._tabs.get(page_or_tab_id)
        tab_id = self._page_to_id.get(page_or_tab_id)
        return self._tabs.get(tab_id) if tab_id else None

    def get_page(self, tab_id: str) -> Optional[Any]:
        """Retrieves Playwright Page reference by tab_id."""
        record = self._tabs.get(tab_id)
        return record.page_ref if record else None

    def is_protected(self, page_or_tab_id: Any) -> bool:
        """
        Returns True if the tab is explicitly protected or points to the JARVIS control server.
        """
        record = self.get_tab(page_or_tab_id)
        if not record:
            # Fallback URL check if page object has url attribute
            if hasattr(page_or_tab_id, "url"):
                return self.is_server_url(page_or_tab_id.url)
            return False
        return record.protected or self.is_server_url(record.url)

    def list_tabs(self) -> List[Dict[str, Any]]:
        """Returns metadata list of all active registered tabs."""
        return [tab.to_dict() for tab in self._tabs.values()]

    def get_tabs_by_owner(self, owner: str) -> List[TabRecord]:
        """Returns all tabs registered to a specific owner."""
        return [tab for tab in self._tabs.values() if tab.owner == owner or tab.owner == f"agent:{owner}"]

    def get_tabs_by_task(self, task_id: str) -> List[TabRecord]:
        """Returns all tabs created under a given task_id."""
        return [tab for tab in self._tabs.values() if tab.parent_task_id == task_id or tab.owner == task_id or tab.owner == f"agent:{task_id}"]

    def get_active_agent_tabs(self, task_id: Optional[str] = None) -> List[TabRecord]:
        """Returns non-protected tabs owned by an agent or specific task."""
        tabs = []
        for tab in self._tabs.values():
            if tab.protected or self.is_server_url(tab.url):
                continue
            if task_id:
                if tab.is_owned_by(task_id):
                    tabs.append(tab)
            else:
                if tab.owner.startswith("agent:") or tab.owner == "research_agent" or tab.owner == "browser_agent":
                    tabs.append(tab)
        return tabs
