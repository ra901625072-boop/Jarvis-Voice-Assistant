import pytest
import asyncio
from ai.contracts.envelope import AgentTask, ExecutionContext
from modules.execution.task_visibility_engine import TaskVisibilityEngine
from modules.execution.tool_visibility_registry import ToolVisibilityRegistry
from modules.task.state_manager import SubTask


def test_task_visibility_classification_foreground():
    ctx1 = TaskVisibilityEngine.classify("open WhatsApp chat with Karan", "open_chat_in_browser")
    assert ctx1 == ExecutionContext.FOREGROUND

    ctx2 = TaskVisibilityEngine.classify("show me the Gmail inbox on screen", "read_inbox")
    assert ctx2 == ExecutionContext.FOREGROUND

    ctx3 = TaskVisibilityEngine.classify("play Iron Man trailer on screen", "play_youtube_video")
    assert ctx3 == ExecutionContext.FOREGROUND


def test_task_visibility_classification_background():
    ctx1 = TaskVisibilityEngine.classify("send WhatsApp message hello to Karan", "send_social_message")
    assert ctx1 == ExecutionContext.BACKGROUND

    ctx2 = TaskVisibilityEngine.classify("research AI topics and create report", "research_topic")
    assert ctx2 == ExecutionContext.BACKGROUND

    ctx3 = TaskVisibilityEngine.classify("check my unread emails silently", "read_inbox")
    assert ctx3 == ExecutionContext.BACKGROUND


def test_task_visibility_explicit_override():
    ctx1 = TaskVisibilityEngine.classify("anything", "tool_x", {"execution_context": "foreground"})
    assert ctx1 == ExecutionContext.FOREGROUND

    ctx2 = TaskVisibilityEngine.classify("anything", "tool_y", {"execution_context": "background"})
    assert ctx2 == ExecutionContext.BACKGROUND


def test_grounded_vision_structural_signal():
    ctx1, conf, reason = TaskVisibilityEngine.classify_detailed(
        "read text on screen", "custom_tool", {}, requires_grounded_vision=True
    )
    assert ctx1 == ExecutionContext.FOREGROUND
    assert conf >= 0.95
    assert "grounded screen vision" in reason


def test_tool_visibility_registry_conditional_rules():
    # Browser action with headless=True -> BACKGROUND
    ctx_bg = TaskVisibilityEngine.classify("scrape web page", "browser_action", {"headless": True})
    assert ctx_bg == ExecutionContext.BACKGROUND

    # Command executing notepad -> FOREGROUND
    ctx_gui = TaskVisibilityEngine.classify("open notepad editor", "execute_command", {"command": "notepad.exe"})
    assert ctx_gui == ExecutionContext.FOREGROUND

    # Command executing CLI -> BACKGROUND
    ctx_cli = TaskVisibilityEngine.classify("list directory files", "execute_command", {"command": "dir"})
    assert ctx_cli == ExecutionContext.BACKGROUND


def test_subtask_and_envelope_context_fields():
    task = AgentTask(task_type="send_message", execution_context=ExecutionContext.BACKGROUND.value)
    assert task.execution_context == "background"

    subtask = SubTask(description="Send message", tool_name="send_social_message", execution_context="background")
    d = subtask.to_dict()
    assert d["execution_context"] == "background"
