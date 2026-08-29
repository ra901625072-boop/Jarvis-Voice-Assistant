"""
modules/browser/perception — Perception Triad for Autonomous Browser Agent.
Combines Semantic Accessibility Tree, Interactive DOM extraction, and Visual snapshots.
"""

from modules.browser.perception.accessibility import AccessibilityParser, A11yNode
from modules.browser.perception.dom_reader import DOMReader, DOMElement
from modules.browser.perception.visual_sensor import VisualSensor
from modules.browser.perception.engine import BrowserPerceptionEngine, PageObservation

__all__ = [
    "AccessibilityParser",
    "A11yNode",
    "DOMReader",
    "DOMElement",
    "VisualSensor",
    "BrowserPerceptionEngine",
    "PageObservation",
]
