"""
modules/browser/perception/engine.py — Unified Browser Perception Engine.

Aggregates page metadata, accessibility tree, interactive DOM structure, and visual snapshots
into a unified PageObservation data object for the Browser Agent.
"""

import time
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from modules.browser.perception.accessibility import AccessibilityParser, A11yNode
from modules.browser.perception.dom_reader import DOMReader, DOMElement
from modules.browser.perception.visual_sensor import VisualSensor

logger = logging.getLogger("JARVIS.Browser.PerceptionEngine")


@dataclass
class PageObservation:
    """Complete snapshot of the current browser page state."""
    tab_id: str
    url: str
    title: str
    is_loading: bool = False
    status_code: Optional[int] = 200
    a11y_tree: List[A11yNode] = field(default_factory=list)
    interactive_elements: List[DOMElement] = field(default_factory=list)
    screenshot_path: Optional[str] = None
    captured_at: float = field(default_factory=time.time)

    def to_prompt_context(self) -> str:
        """Renders a concise, token-efficient observation summary for the LLM."""
        lines = [
            f"=== CURRENT BROWSER STATE ===",
            f"Tab ID: {self.tab_id}",
            f"URL: {self.url}",
            f"Title: {self.title}",
            "",
            "--- SEMANTIC ACCESSIBILITY TREE ---",
        ]
        if self.a11y_tree:
            lines.append(AccessibilityParser.format_for_prompt(self.a11y_tree))
        else:
            lines.append("(No semantic nodes extracted)")

        lines.extend([
            "",
            "--- INTERACTIVE DOM ELEMENTS ---",
        ])
        if self.interactive_elements:
            lines.append(DOMReader.format_for_prompt(self.interactive_elements))
        else:
            lines.append("(No interactive DOM elements extracted)")

        return "\n".join(lines)


class BrowserPerceptionEngine:
    """
    Coordinates multi-layered perception extraction across accessibility, DOM, and visual sensors.
    """

    def __init__(self, visual_sensor: Optional[VisualSensor] = None):
        self.visual_sensor = visual_sensor or VisualSensor()

    async def observe(
        self,
        page: Any,
        tab_id: str = "current",
        capture_screenshot: bool = False,
    ) -> PageObservation:
        """
        Executes a full perception sweep of the provided Playwright page.
        """
        if not page:
            return PageObservation(
                tab_id=tab_id,
                url="about:blank",
                title="No Page Available",
                is_loading=False,
            )

        url = "about:blank"
        title = ""
        try:
            url = page.url or "about:blank"
            title = await page.title()
        except Exception:
            pass

        # 1. Capture Accessibility Tree
        a11y_nodes = await AccessibilityParser.extract_from_page(page)

        # 2. Capture Interactive DOM Elements
        dom_elements = await DOMReader.extract_interactive_elements(page)

        # 3. Optional Screenshot Capture
        screenshot_path = None
        if capture_screenshot:
            screenshot_path = await self.visual_sensor.capture_screenshot(page, filename_prefix=f"obs_{tab_id}")

        return PageObservation(
            tab_id=tab_id,
            url=url,
            title=title,
            is_loading=False,
            a11y_tree=a11y_nodes,
            interactive_elements=dom_elements,
            screenshot_path=screenshot_path,
            captured_at=time.time(),
        )
