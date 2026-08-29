"""
modules/browser/perception/accessibility.py — Semantic Accessibility Tree Extractor.

Parses Playwright's accessibility snapshot into a compact, token-efficient representation
focusing on interactive semantic roles (buttons, inputs, links, headings, modals, dialogs).
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger("JARVIS.Browser.A11y")


@dataclass
class A11yNode:
    """Represents a simplified semantic accessibility node."""
    role: str
    name: str = ""
    value: Optional[str] = None
    description: Optional[str] = None
    focused: bool = False
    disabled: bool = False
    checked: Optional[bool] = None
    expanded: Optional[bool] = None
    selected: Optional[bool] = None
    level: Optional[int] = None
    children: List["A11yNode"] = field(default_factory=list)

    @property
    def is_interactive(self) -> bool:
        interactive_roles = {
            "button", "link", "textbox", "searchbox", "checkbox", "radio",
            "combobox", "listbox", "option", "menuitem", "tab", "switch",
            "spinbutton", "slider"
        }
        return self.role in interactive_roles

    def to_locator_hint(self) -> str:
        """Returns a Playwright role-based locator hint."""
        if self.name:
            # Escape quotes in name
            clean_name = self.name.replace('"', '\\"')
            return f'role={self.role}[name="{clean_name}"]'
        return f'role={self.role}'

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "role": self.role,
            "locator": self.to_locator_hint(),
        }
        if self.name:
            d["name"] = self.name
        if self.value is not None:
            d["value"] = self.value
        if self.focused:
            d["focused"] = True
        if self.disabled:
            d["disabled"] = True
        if self.checked is not None:
            d["checked"] = self.checked
        if self.expanded is not None:
            d["expanded"] = self.expanded
        if self.selected is not None:
            d["selected"] = self.selected
        if self.level is not None:
            d["level"] = self.level
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


class AccessibilityParser:
    """
    Parses and filters raw accessibility trees into clean LLM-friendly structures.
    """

    INTERESTING_ROLES = {
        "button", "link", "textbox", "searchbox", "checkbox", "radio",
        "combobox", "listbox", "option", "menu", "menuitem", "tab", "tabpanel",
        "dialog", "alert", "heading", "article", "main", "navigation", "form",
        "table", "row", "cell", "switch", "slider", "img"
    }

    @classmethod
    async def extract_from_page(cls, page: Any, max_depth: int = 6) -> List[A11yNode]:
        """
        Extracts and parses accessibility snapshot from a Playwright Page instance.
        """
        if not page:
            return []

        try:
            raw_snapshot = await page.accessibility.snapshot(interesting_only=True)
            if not raw_snapshot:
                return []
            return cls.parse_raw_tree(raw_snapshot, max_depth=max_depth)
        except Exception as e:
            logger.warning(f"Failed to capture accessibility snapshot: {e}")
            return []

    @classmethod
    def parse_raw_tree(cls, raw_node: Dict[str, Any], depth: int = 0, max_depth: int = 6) -> List[A11yNode]:
        """Recursively filters and transforms raw Playwright a11y tree."""
        if depth > max_depth or not raw_node:
            return []

        role = raw_node.get("role", "").lower()
        name = raw_node.get("name", "").strip()
        value = raw_node.get("value")
        
        # Process children
        parsed_children: List[A11yNode] = []
        for child in raw_node.get("children", []):
            parsed_children.extend(cls.parse_raw_tree(child, depth=depth + 1, max_depth=max_depth))

        # Check if current node is worth keeping
        has_content = bool(name or value or parsed_children)
        is_relevant_role = role in cls.INTERESTING_ROLES

        if is_relevant_role and has_content:
            node = A11yNode(
                role=role,
                name=name,
                value=str(value) if value is not None else None,
                description=raw_node.get("description"),
                focused=bool(raw_node.get("focused", False)),
                disabled=bool(raw_node.get("disabled", False)),
                checked=raw_node.get("checked"),
                expanded=raw_node.get("expanded"),
                selected=raw_node.get("selected"),
                level=raw_node.get("level"),
                children=parsed_children,
            )
            return [node]

        # If container node is generic, lift up its children
        return parsed_children

    @classmethod
    def format_for_prompt(cls, nodes: List[A11yNode], indent: int = 0) -> str:
        """Formats the accessibility nodes into an indented readable text representation for LLM."""
        lines = []
        prefix = "  " * indent
        for node in nodes:
            state_tokens = []
            if node.focused:
                state_tokens.append("[focused]")
            if node.disabled:
                state_tokens.append("[disabled]")
            if node.checked is True:
                state_tokens.append("[checked]")
            if node.expanded is True:
                state_tokens.append("[expanded]")
            if node.selected is True:
                state_tokens.append("[selected]")
            if node.value:
                state_tokens.append(f'val="{node.value}"')
            
            states = " " + " ".join(state_tokens) if state_tokens else ""
            name_str = f' "{node.name}"' if node.name else ""
            line = f"{prefix}- {node.role}{name_str}{states} -> locator: {node.to_locator_hint()}"
            lines.append(line)
            
            if node.children:
                lines.append(cls.format_for_prompt(node.children, indent=indent + 1))
                
        return "\n".join(lines)
