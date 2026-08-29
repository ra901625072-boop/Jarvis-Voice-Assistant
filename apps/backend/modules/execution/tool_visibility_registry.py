"""
tool_visibility_registry.py — Declarative Tool Visibility Registry.

Defines the default visibility (FOREGROUND vs BACKGROUND) for all JARVIS tools,
plus conditional decision rules for tools whose visibility depends on execution arguments.
"""
from typing import Any, Dict, Optional, Tuple, Union
from ai.contracts.envelope import ExecutionContext


# Primary mapping of tool_name -> visibility mode (or rule dict)
TOOL_VISIBILITY: Dict[str, Union[str, Dict[str, Any]]] = {
    # ── Interactive / Window / UI Tools (FOREGROUND) ──
    "open_chat_in_browser": "foreground",
    "launch_app": "foreground",
    "play_youtube_video": "foreground",
    "bring_window_to_front": "foreground",
    "open_website": "foreground",
    "inspect_screen": "foreground",
    "analyze_screen": "foreground",
    "analyze_screen_on_demand": "foreground",
    "analyze_screen_with_som": "foreground",
    "click_element": "foreground",
    "type_text": "foreground",
    "minimize_window": "foreground",
    "maximize_window": "foreground",
    "restore_window": "foreground",
    "close_window": "foreground",
    "focus_window": "foreground",
    "switch_window": "foreground",
    "show_desktop": "foreground",
    "mouse_click": "foreground",
    "mouse_move": "foreground",
    "mouse_scroll": "foreground",
    "keyboard_press": "foreground",
    "keyboard_type": "foreground",

    # ── Headless / Silent Data Processing Tools (BACKGROUND) ──
    "send_social_message": "background",
    "send_email": "background",
    "read_inbox": "background",
    "read_conversation": "background",
    "get_unread_chats": "background",
    "read_social_messages": "background",
    "connect_social_account": "background",
    "get_social_status": "background",
    "research_topic": "background",
    "create_file": "background",
    "create_folder": "background",
    "read_file": "background",
    "delete_file": "background",
    "list_directory": "background",
    "generate_personalized_reply": "background",
    "schedule_post": "background",
    "resolve_contact": "background",
    "translate_text": "background",
    "verify_execution": "background",
    "list_background_tasks": "background",
    "get_background_task_status": "background",
    "cancel_background_task": "background",
    "copy_to_clipboard": "background",
    "get_from_clipboard": "background",
    "clear_clipboard": "background",
    "shutdown_system": "background",
    "restart_system": "background",
    "sleep_system": "background",
    "lock_pc": "background",
    "logout_user": "background",
    "get_weather": "background",
    "get_time": "background",
    "calculate": "background",
    "save_memory": "background",
    "recall_memory": "background",
    "forget_memory": "background",

    # ── Conditional Tools ──
    "search_web": {"default": "background"},
    "browser_action": {"default": "conditional", "rule": "foreground_unless_headless"},
    "execute_command": {"default": "conditional", "rule": "foreground_if_gui_app"},
    "run_terminal_command": {"default": "conditional", "rule": "foreground_if_gui_app"},
    "run_python_code": {"default": "conditional", "rule": "foreground_if_gui_app"},
    "take_screenshot": {"default": "background"},
}


class ToolVisibilityRegistry:
    """
    Registry wrapper providing lookup logic and conditional rule evaluation.
    """

    @classmethod
    def get_visibility(
        cls, tool_name: str, args: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[ExecutionContext], float, str]:
        """
        Look up tool visibility mode in the registry.

        Returns:
            (ExecutionContext, confidence_score, reason) or (None, 0.0, "not_found")
        """
        tool = str(tool_name).lower().strip()
        if not tool or tool not in TOOL_VISIBILITY:
            return None, 0.0, f"Tool '{tool_name}' not in registry"

        entry = TOOL_VISIBILITY[tool]

        # Handle simple string mapping
        if isinstance(entry, str):
            if entry == "foreground":
                return ExecutionContext.FOREGROUND, 0.95, f"Registry lookup: '{tool}' is static FOREGROUND"
            if entry == "background":
                return ExecutionContext.BACKGROUND, 0.95, f"Registry lookup: '{tool}' is static BACKGROUND"

        # Handle conditional dict entry
        if isinstance(entry, dict):
            payload = args or {}
            rule = entry.get("rule")

            if rule == "foreground_unless_headless":
                if payload.get("headless") is True or payload.get("background") is True:
                    return ExecutionContext.BACKGROUND, 0.95, f"Registry conditional rule '{rule}': headless=True"
                return ExecutionContext.FOREGROUND, 0.95, f"Registry conditional rule '{rule}': interactive browser"

            if rule == "foreground_if_gui_app":
                cmd = str(payload.get("command") or payload.get("code") or "").lower()
                gui_indicators = ("notepad", "calc", "explorer", "start ", "chrome", "edge", "vlc", "plt.show")
                if any(gui in cmd for gui in gui_indicators):
                    return ExecutionContext.FOREGROUND, 0.90, f"Registry conditional rule '{rule}': launches GUI"
                return ExecutionContext.BACKGROUND, 0.90, f"Registry conditional rule '{rule}': silent command"

            default_mode = entry.get("default", "background")
            if default_mode == "foreground":
                return ExecutionContext.FOREGROUND, 0.85, f"Registry default for conditional tool '{tool}'"
            return ExecutionContext.BACKGROUND, 0.85, f"Registry default for conditional tool '{tool}'"

        return None, 0.0, f"Registry entry for '{tool_name}' unresolved"
