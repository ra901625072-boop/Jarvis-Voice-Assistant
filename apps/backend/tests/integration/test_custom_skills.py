"""
tests/integration/test_custom_skills.py — Integration tests for Markdown skill parsing and loader.
"""
import pytest
from modules.skills.markdown_loader import parse_markdown


class TestCustomSkillsIntegration:
    def test_parse_markdown_with_frontmatter(self):
        """Markdown loader correctly extracts YAML metadata and body instructions."""
        sample_md = """---
name: Weather Skill
description: Fetches current temperature and forecast
version: 1.0.0
author: Developer
---

# Instructions
When the user asks for weather, call the weather API.
"""
        parsed = parse_markdown(sample_md)
        assert parsed is not None
        assert parsed["metadata"]["name"] == "Weather Skill"
        assert parsed["metadata"]["version"] == "1.0.0"
        assert "call the weather API" in parsed["body"]

    def test_parse_markdown_empty_and_invalid(self):
        """Empty or invalid markdown returns safe defaults without throwing exceptions."""
        empty_res = parse_markdown("")
        assert empty_res == {"metadata": {}, "body": ""}

        plain_text = "Just instructions without frontmatter."
        plain_res = parse_markdown(plain_text)
        assert plain_res["body"] == plain_text
