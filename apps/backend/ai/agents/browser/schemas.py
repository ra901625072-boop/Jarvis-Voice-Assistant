"""
ai/agents/browser/schemas.py — Action and Observation schemas for Autonomous Browser Agent.
"""

from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from modules.browser.actions.vocabulary import BrowserActionType, BrowserAction


class BrowserActionSchema:
    """Validator and normalizer for Browser Agent actions."""
    
    ALLOWED_ACTIONS = {action.value for action in BrowserActionType}

    @classmethod
    def validate_and_normalize(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            raise TypeError("Action payload must be a dictionary.")

        browser_action = BrowserAction.from_dict(data)
        
        # Build normalized dictionary backward-compatible with older callers
        normalized = {
            "action": browser_action.action.value,
            "selector": browser_action.target,
            "target": browser_action.target,
            "text": browser_action.text,
            "url": browser_action.url,
            "key": browser_action.key,
            "direction": browser_action.direction,
            "amount_px": browser_action.amount_px,
            "value": browser_action.value,
            "timeout_ms": browser_action.timeout_ms,
            "reason": browser_action.reason,
            "metadata": browser_action.metadata,
        }
        return normalized


class StepExecutionRecord(BaseModel):
    step_number: int
    action: str
    target: Optional[str] = None
    reason: str = ""
    success: bool
    result_message: str
    pre_url: Optional[str] = None
    post_url: Optional[str] = None
    verification_passed: bool = True
    verification_notes: str = ""
    timestamp: float
    screenshot_path: Optional[str] = None


class AutomationWorkflowResult(BaseModel):
    success: bool
    objective: str
    total_steps: int
    history: List[StepExecutionRecord] = Field(default_factory=list)
    final_url: Optional[str] = None
    final_title: Optional[str] = None
    extracted_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
