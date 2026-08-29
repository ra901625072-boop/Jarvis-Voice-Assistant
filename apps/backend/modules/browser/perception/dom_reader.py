"""
modules/browser/perception/dom_reader.py — Interactive DOM Structure Reader.

Extracts visible, interactive elements from the live DOM with CSS and XPath selectors,
bounding boxes, attributes, and input states.
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger("JARVIS.Browser.DOMReader")


@dataclass
class DOMElement:
    """Represents an interactive DOM element extracted from the page."""
    index: int
    tag: str
    selector: str
    text: str = ""
    element_type: str = ""
    name: str = ""
    id_attr: str = ""
    placeholder: str = ""
    aria_label: str = ""
    href: str = ""
    is_visible: bool = True
    is_enabled: bool = True
    rect: Optional[Dict[str, float]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "index": self.index,
            "tag": self.tag,
            "selector": self.selector,
        }
        if self.text:
            d["text"] = self.text
        if self.element_type:
            d["type"] = self.element_type
        if self.id_attr:
            d["id"] = self.id_attr
        if self.name:
            d["name"] = self.name
        if self.placeholder:
            d["placeholder"] = self.placeholder
        if self.aria_label:
            d["aria_label"] = self.aria_label
        if self.href:
            d["href"] = self.href
        return d


class DOMReader:
    """
    Extracts structured interactive DOM elements using evaluated in-page JavaScript.
    """

    EXTRACTOR_JS = """
    (() => {
        const interactiveSelectors = [
            'button', 'a[href]', 'input', 'textarea', 'select',
            '[role="button"]', '[role="link"]', '[role="checkbox"]',
            '[role="menuitem"]', '[role="tab"]', '[role="combobox"]',
            '[contenteditable="true"]'
        ];

        const elements = Array.from(document.querySelectorAll(interactiveSelectors.join(',')));
        const results = [];
        let index = 0;

        for (const el of elements) {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            
            // Check visibility
            const isVisible = !!(rect.width > 0 && rect.height > 0 && 
                                 style.visibility !== 'hidden' && 
                                 style.display !== 'none' && 
                                 style.opacity !== '0');
            
            if (!isVisible) continue;

            // Generate robust selector
            let selector = '';
            if (el.id) {
                selector = `#${CSS.escape(el.id)}`;
            } else if (el.name && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT')) {
                selector = `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;
            } else if (el.getAttribute('data-testid')) {
                selector = `[data-testid="${CSS.escape(el.getAttribute('data-testid'))}"]`;
            } else if (el.getAttribute('aria-label')) {
                selector = `[aria-label="${CSS.escape(el.getAttribute('aria-label'))}"]`;
            } else if (el.placeholder) {
                selector = `${el.tagName.toLowerCase()}[placeholder="${CSS.escape(el.placeholder)}"]`;
            } else if (el.className && typeof el.className === 'string') {
                const firstClass = el.className.trim().split(/\\s+/)[0];
                if (firstClass && !firstClass.includes(':')) {
                    selector = `${el.tagName.toLowerCase()}.${CSS.escape(firstClass)}`;
                }
            }
            
            if (!selector) {
                selector = el.tagName.toLowerCase();
            }

            const text = (el.innerText || el.textContent || el.value || '').trim().replace(/\\s+/g, ' ').substring(0, 100);
            
            results.push({
                index: index++,
                tag: el.tagName.toLowerCase(),
                selector: selector,
                text: text,
                element_type: el.type || '',
                name: el.name || '',
                id_attr: el.id || '',
                placeholder: el.placeholder || '',
                aria_label: el.getAttribute('aria-label') || '',
                href: el.href ? el.href.substring(0, 120) : '',
                is_visible: true,
                is_enabled: !el.disabled,
                rect: {
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height)
                }
            });

            if (results.length >= 60) break; // Limit to top 60 interactive elements to preserve token budget
        }

        return results;
    })()
    """

    @classmethod
    async def extract_interactive_elements(cls, page: Any) -> List[DOMElement]:
        """Extracts visible interactive elements from page."""
        if not page:
            return []

        try:
            raw_elements = await page.evaluate(cls.EXTRACTOR_JS)
            if not isinstance(raw_elements, list):
                return []

            elements = []
            for item in raw_elements:
                elements.append(
                    DOMElement(
                        index=item.get("index", 0),
                        tag=item.get("tag", ""),
                        selector=item.get("selector", ""),
                        text=item.get("text", ""),
                        element_type=item.get("element_type", ""),
                        name=item.get("name", ""),
                        id_attr=item.get("id_attr", ""),
                        placeholder=item.get("placeholder", ""),
                        aria_label=item.get("aria_label", ""),
                        href=item.get("href", ""),
                        is_visible=item.get("is_visible", True),
                        is_enabled=item.get("is_enabled", True),
                        rect=item.get("rect"),
                    )
                )
            return elements
        except Exception as e:
            logger.warning(f"DOM extraction failed: {e}")
            return []

    @classmethod
    def format_for_prompt(cls, elements: List[DOMElement]) -> str:
        """Formats the interactive DOM elements into clean JSON-like YAML lines."""
        lines = []
        for el in elements:
            parts = [f"[{el.index}] <{el.tag}>"]
            if el.id_attr:
                parts.append(f'id="#{el.id_attr}"')
            if el.selector:
                parts.append(f'selector="{el.selector}"')
            if el.text:
                parts.append(f'text="{el.text}"')
            if el.placeholder:
                parts.append(f'placeholder="{el.placeholder}"')
            if el.name:
                parts.append(f'name="{el.name}"')
            if el.aria_label:
                parts.append(f'aria-label="{el.aria_label}"')
            if el.element_type:
                parts.append(f'type="{el.element_type}"')
            lines.append(" ".join(parts))
        return "\n".join(lines)
