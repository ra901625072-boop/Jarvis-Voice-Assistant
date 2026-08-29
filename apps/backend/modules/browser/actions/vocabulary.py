"""
modules/browser/actions/vocabulary.py — Strongly-typed Action Vocabulary and Data Schemas.

Defines the controlled action primitives supported by the JARVIS Browser Subsystem.
"""

from enum import Enum
from typing import Dict, Any, Optional, Union
from pydantic import BaseModel, Field


class BrowserActionType(str, Enum):
    # Navigation
    NAVIGATE = "navigate"
    GO_BACK = "go_back"
    GO_FORWARD = "go_forward"
    RELOAD = "reload"
    NEW_TAB = "new_tab"
    CLOSE_TAB = "close_tab"
    SWITCH_TAB = "switch_tab"
    
    # Interaction
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    TYPE = "type"
    CLEAR = "clear"
    SCROLL = "scroll"
    HOVER = "hover"
    SELECT_OPTION = "select_option"
    PRESS_KEY = "press_key"
    
    # Utility & Observation
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    EXTRACT = "extract"
    COMPLETED = "completed"


class BrowserAction(BaseModel):
    """Normalized structured browser action payload."""
    action: BrowserActionType
    target: Optional[str] = Field(default=None, description="CSS selector, XPath, role locator, or tab identifier")
    text: Optional[str] = Field(default=None, description="Text string to type into input element")
    url: Optional[str] = Field(default=None, description="URL for navigation or new tab")
    key: Optional[str] = Field(default=None, description="Key name to press, e.g. 'Enter', 'Escape', 'Tab'")
    direction: Optional[str] = Field(default="down", description="Scroll direction: 'up', 'down', 'top', 'bottom'")
    amount_px: Optional[int] = Field(default=400, description="Pixels to scroll")
    value: Optional[str] = Field(default=None, description="Option value for dropdown select")
    timeout_ms: Optional[int] = Field(default=10000, description="Action timeout in milliseconds")
    reason: Optional[str] = Field(default="", description="Chain-of-thought rationale from planner")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BrowserAction":
        """Normalizes and constructs a BrowserAction from raw LLM output."""
        if not isinstance(data, dict):
            raise TypeError("Action input must be a dictionary.")

        raw_action = str(data.get("action", "")).strip().lower()
        if not raw_action:
            raise ValueError("Missing 'action' field.")

        # Map aliases
        action_map = {
            "open_url": BrowserActionType.NAVIGATE,
            "goto": BrowserActionType.NAVIGATE,
            "navigate": BrowserActionType.NAVIGATE,
            "click": BrowserActionType.CLICK,
            "double_click": BrowserActionType.DOUBLE_CLICK,
            "type": BrowserActionType.TYPE,
            "fill": BrowserActionType.TYPE,
            "clear": BrowserActionType.CLEAR,
            "scroll": BrowserActionType.SCROLL,
            "hover": BrowserActionType.HOVER,
            "select": BrowserActionType.SELECT_OPTION,
            "select_option": BrowserActionType.SELECT_OPTION,
            "press": BrowserActionType.PRESS_KEY,
            "press_key": BrowserActionType.PRESS_KEY,
            "wait": BrowserActionType.WAIT,
            "sleep": BrowserActionType.WAIT,
            "screenshot": BrowserActionType.SCREENSHOT,
            "extract": BrowserActionType.EXTRACT,
            "new_tab": BrowserActionType.NEW_TAB,
            "close_tab": BrowserActionType.CLOSE_TAB,
            "switch_tab": BrowserActionType.SWITCH_TAB,
            "back": BrowserActionType.GO_BACK,
            "go_back": BrowserActionType.GO_BACK,
            "forward": BrowserActionType.GO_FORWARD,
            "go_forward": BrowserActionType.GO_FORWARD,
            "reload": BrowserActionType.RELOAD,
            "refresh": BrowserActionType.RELOAD,
            "done": BrowserActionType.COMPLETED,
            "finish": BrowserActionType.COMPLETED,
            "completed": BrowserActionType.COMPLETED,
        }

        if raw_action not in action_map:
            raise ValueError(f"Unknown action '{raw_action}'. Allowed: {[a.value for a in BrowserActionType]}")

        action_enum = action_map[raw_action]
        target = data.get("target") or data.get("selector") or data.get("locator") or data.get("tab_id")
        text = data.get("text") or data.get("value") if action_enum == BrowserActionType.TYPE else None
        url = data.get("url") or data.get("href")
        key = data.get("key") or data.get("key_name")
        direction = data.get("direction", "down")
        amount_px = data.get("amount_px") or data.get("amount") or 400
        value = data.get("value") if action_enum == BrowserActionType.SELECT_OPTION else None
        timeout_ms = data.get("timeout_ms") or data.get("timeout") or 10000
        reason = data.get("reason", "")

        return cls(
            action=action_enum,
            target=str(target).strip() if target else None,
            text=str(text) if text is not None else None,
            url=str(url).strip() if url else None,
            key=str(key).strip() if key else None,
            direction=str(direction).strip().lower(),
            amount_px=int(amount_px) if amount_px else 400,
            value=str(value).strip() if value else None,
            timeout_ms=int(timeout_ms) if timeout_ms else 10000,
            reason=str(reason).strip(),
            metadata=data.get("metadata", {}),
        )


class ActionExecutionResult(BaseModel):
    """Result of executing an atomic browser action."""
    action: BrowserActionType
    success: bool
    message: str
    target: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    duration_ms: float = 0.0
    error: Optional[str] = None
    screenshot_path: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success
