"""
tests/unit/test_browser_perception.py — Unit Tests for Accessibility Tree and DOM Extraction.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from modules.browser.perception.accessibility import AccessibilityParser, A11yNode
from modules.browser.perception.dom_reader import DOMReader, DOMElement
from modules.browser.perception.engine import PageObservation


class TestBrowserPerception:
    def test_a11y_node_interactive_and_locator_hint(self):
        btn_node = A11yNode(role="button", name="Search Google")
        assert btn_node.is_interactive is True
        assert btn_node.to_locator_hint() == 'role=button[name="Search Google"]'

        textbox_node = A11yNode(role="textbox", name="Query")
        assert textbox_node.is_interactive is True
        assert textbox_node.to_locator_hint() == 'role=textbox[name="Query"]'

        heading_node = A11yNode(role="heading", name="Welcome", level=1)
        assert heading_node.is_interactive is False
        assert heading_node.to_locator_hint() == 'role=heading[name="Welcome"]'

    def test_parse_raw_tree_filtering(self):
        raw_tree = {
            "role": "WebArea",
            "name": "Test Page",
            "children": [
                {
                    "role": "generic",
                    "children": [
                        {
                            "role": "button",
                            "name": "Submit",
                            "disabled": False,
                        },
                        {
                            "role": "textbox",
                            "name": "Username",
                            "value": "jarvis_admin",
                        },
                    ]
                }
            ]
        }

        nodes = AccessibilityParser.parse_raw_tree(raw_tree)
        assert len(nodes) >= 1
        prompt_repr = AccessibilityParser.format_for_prompt(nodes)
        assert "Submit" in prompt_repr
        assert "Username" in prompt_repr

    def test_dom_element_formatting(self):
        elements = [
            DOMElement(
                index=0,
                tag="button",
                selector="#submit-btn",
                text="Submit",
                id_attr="submit-btn",
            ),
            DOMElement(
                index=1,
                tag="input",
                selector="input[name='q']",
                name="q",
                placeholder="Search...",
                element_type="text",
            ),
        ]

        formatted = DOMReader.format_for_prompt(elements)
        assert "[0] <button>" in formatted
        assert 'id="#submit-btn"' in formatted
        assert "[1] <input>" in formatted
        assert 'name="q"' in formatted

    def test_page_observation_to_prompt_context(self):
        obs = PageObservation(
            tab_id="tab_123",
            url="https://www.google.com",
            title="Google",
            a11y_tree=[A11yNode(role="button", name="Search")],
            interactive_elements=[DOMElement(index=0, tag="button", selector="#btn", text="Search")],
        )

        context = obs.to_prompt_context()
        assert "Tab ID: tab_123" in context
        assert "URL: https://www.google.com" in context
        assert "SEMANTIC ACCESSIBILITY TREE" in context
        assert "INTERACTIVE DOM ELEMENTS" in context
