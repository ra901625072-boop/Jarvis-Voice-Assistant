"""
task_visibility_engine.py — Task Visibility & Execution Context Engine.

Determines whether a user task should be executed in the FOREGROUND (Visual, Interactive,
On-Screen) or in the BACKGROUND (Headless, Silent, Non-Disruptive Data Processing).
"""
import logging
from typing import Any, Dict, Optional, Tuple
from ai.contracts.envelope import ExecutionContext
from modules.execution.tool_visibility_registry import ToolVisibilityRegistry

logger = logging.getLogger("JARVIS.TaskVisibilityEngine")


class TaskVisibilityEngine:
    """
    Classifies task intent into ExecutionContext.FOREGROUND or ExecutionContext.BACKGROUND
    using an ordered multi-signal decision pipeline.
    """

    EXPLICIT_FG_PHRASES = (
        "on screen", "in front", "front of me", "show me", "open a window",
        "visually", "let me see", "watch this", "on the display", "open ", "show ", "launch ", "play "
    )

    EXPLICIT_BG_PHRASES = (
        "in background", "in the background", "silently", "quietly",
        "don't open a window", "headless", "without opening", "in bg"
    )

    @classmethod
    def classify_detailed(
        cls,
        goal_or_query: str = "",
        tool_name: str = "",
        args: Optional[Dict[str, Any]] = None,
        requires_grounded_vision: Optional[bool] = None
    ) -> Tuple[ExecutionContext, float, str]:
        """
        Classify task intent returning (ExecutionContext, confidence_score, reason).
        """
        text = str(goal_or_query).lower().strip()
        tool = str(tool_name).lower().strip()
        payload = args or {}

        # ── Step 0: Explicit Override in payload ──
        explicit_mode = payload.get("execution_context") or payload.get("mode")
        if explicit_mode:
            m = str(explicit_mode).lower().strip()
            if m in ("foreground", "fg", "visual"):
                return ExecutionContext.FOREGROUND, 1.0, "Step 0: Explicit override in payload (FOREGROUND)"
            if m in ("background", "bg", "silent", "headless"):
                return ExecutionContext.BACKGROUND, 1.0, "Step 0: Explicit override in payload (BACKGROUND)"

        # ── Step 1: Grounded Vision / Structural Signal ──
        grounded = requires_grounded_vision
        if grounded is None:
            grounded = payload.get("requires_grounded_vision")
        if grounded is True:
            return ExecutionContext.FOREGROUND, 0.95, "Step 1: Task requires grounded screen vision pipeline (FOREGROUND)"

        # ── Step 2: Explicit User Phrasing Override in Query ──
        if any(phrase in text for phrase in cls.EXPLICIT_BG_PHRASES):
            return ExecutionContext.BACKGROUND, 0.90, "Step 2: Query contains explicit background phrase"
        if any(phrase in text for phrase in cls.EXPLICIT_FG_PHRASES):
            return ExecutionContext.FOREGROUND, 0.90, "Step 2: Query contains explicit foreground phrase"

        # ── Step 3: Declarative Tool Visibility Registry ──
        reg_ctx, reg_conf, reg_reason = ToolVisibilityRegistry.get_visibility(tool, payload)
        if reg_ctx is not None:
            return reg_ctx, reg_conf, f"Step 3: {reg_reason}"

        # ── Step 4: Side-Effect Heuristic on Tool Name ──
        if tool.startswith(("send_", "create_", "read_", "fetch_", "search_", "generate_", "list_", "get_", "delete_", "write_")):
            return ExecutionContext.BACKGROUND, 0.65, f"Step 4: Tool name '{tool}' matches silent data verb pattern (BACKGROUND)"
        if tool.startswith(("open_", "launch_", "play_", "focus_", "bring_", "click_", "type_", "press_", "show_")):
            return ExecutionContext.FOREGROUND, 0.65, f"Step 4: Tool name '{tool}' matches visual/UI verb pattern (FOREGROUND)"

        # ── Step 5: Fallback Default ──
        return ExecutionContext.BACKGROUND, 0.50, "Step 5: Fallback default (BACKGROUND)"

    @classmethod
    def classify(
        cls,
        goal_or_query: str = "",
        tool_name: str = "",
        args: Optional[Dict[str, Any]] = None
    ) -> ExecutionContext:
        """
        Backwards-compatible classification entry point returning ExecutionContext.
        """
        ctx, _, _ = cls.classify_detailed(goal_or_query, tool_name, args)
        return ctx
