import os
from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, Optional, Callable, Awaitable
import logging

logger = logging.getLogger("JARVIS.ApprovalEngine")

class RiskLevel(str, Enum):
    LOW = "low"            # Read-only, web search, memory lookup
    MEDIUM = "medium"      # File creation, local package installation
    HIGH = "high"          # System config change, shell script execution, API mutation
    CRITICAL = "critical"  # File deletion, mass email, credential access, external financial operation

@dataclass
class ApprovalRequest:
    action_id: str
    tool_name: str
    risk_level: RiskLevel
    description: str
    params: Dict[str, Any]

class ApprovalEngine:
    def __init__(
        self,
        hitl_callback: Optional[Callable[[ApprovalRequest], Awaitable[bool]]] = None,
        approval_store: Optional[Any] = None,
        task_event_bus: Optional[Any] = None
    ):
        self.hitl_callback = hitl_callback
        self.approval_store = approval_store
        self.task_event_bus = task_event_bus

    def classify_tool_risk(self, tool_name: str, method_name: str, params: Dict[str, Any]) -> RiskLevel:
        tool = tool_name.lower()
        method = method_name.lower()

        if tool in ("systemtools", "system") and method in ("execute_command", "run_shell_script", "run_python_code", "run_terminal_command"):
            return RiskLevel.HIGH

        if tool in ("filetools", "filesystem") and method in ("delete_file", "delete_directory", "format_drive"):
            return RiskLevel.CRITICAL

        # ── Social Media Domain Safety Rules ─────────────────────────────────────
        if tool in ("social_media", "socialmediaagent", "social_media_agent", "social"):
            # Check for bulk/mass actions first
            is_bulk = params.get("bulk", False) or (isinstance(params.get("to"), list) and len(params.get("to")) > 1)
            if is_bulk or method in ("bulk_delete", "bulk_unfollow", "bulk_send", "mass_archive", "delete_all"):
                return RiskLevel.CRITICAL

            # Read-only and lookup tasks (auto-allowed)
            if method in (
                "read_inbox", "read_dms", "list_messages", "list_emails", "inbox", "read_chats", "list_chats",
                "get_unread_chats", "unread_messages", "unread_chats",
                "get_email_details", "read_email", "get_message", "read_thread", "get_thread_messages", "thread_details",
                "search_conversation", "search_emails", "query_emails", "find_emails", "search_chat", "find_chat", "search_messages", "query_messages",
                "get_group_info", "group_details", "read_status_updates", "status_updates", "stories",
                "get_unread_emails", "unread_emails", "get_starred_emails", "starred_emails",
                "get_sent_emails", "sent_emails", "get_attachment", "download_attachment",
                "search_profile", "get_profile_details",
                "find_user", "search_user", "inspect_profile",
                "read_conversation", "get_messages", "who_messaged_what", "inspect_chat",
                "read_notifications", "notifications", "read_activity", "activity_feed",
                "get_recent_followers", "who_followed_last", "recent_followers",
                "get_followers", "list_followers", "get_following", "list_following",
                "create_draft", "draft_reply", "save_draft", "list_drafts", "get_drafts",
                "mark_as_read", "read", "mark_read", "mark_as_unread", "unread", "mark_unread", "star_email", "star", "unstar_email", "unstar",
                "pin_chat", "pin", "unpin_chat", "unpin", "archive_chat", "archive", "unarchive_chat", "unarchive", "mute_chat", "mute", "unmute_chat", "unmute",
                "apply_label", "remove_label", "list_labels", "labels",
                "resolve_contact", "list_contacts", "link_identity", "generate_personalized_reply", "draft_personalized_reply",
                "schedule_post", "list_scheduled_posts", "cancel_scheduled_post",
                "get_status", "connect_account", "disconnect_account", "like", "like_post"
            ):
                return RiskLevel.LOW

            # Relationship state changes
            if method in ("follow_user", "unfollow_user", "follow", "unfollow"):
                return RiskLevel.MEDIUM

            # Outbound communication and publishing mutations (require user confirmation)
            if method in (
                "send_message", "send_chat", "send_dm", "send_email",
                "reply_email", "reply", "reply_message",
                "forward_email", "forward", "forward_message",
                "send_draft", "trash_email", "delete_email", "delete_draft", "clear_chat", "delete_chat", "clear",
                "post_content", "comment_reply", "comment"
            ):
                return RiskLevel.HIGH

        if method in ("read_file", "list_dir", "get_world_state", "analyze_screen", "search_web"):
            return RiskLevel.LOW

        if method in ("write_file", "create_directory"):
            return RiskLevel.MEDIUM

        return RiskLevel.MEDIUM

    async def authorize(
        self,
        tool_name: str,
        method_name: str,
        params: Dict[str, Any],
        task_id: str = "",
        agent_id: str = ""
    ) -> bool:
        risk = self.classify_tool_risk(tool_name, method_name, params)
        logger.info(f"ApprovalEngine evaluating {tool_name}.{method_name} -> RiskLevel: {risk.value}")

        if risk in (RiskLevel.LOW, RiskLevel.MEDIUM):
            return True

        if risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            req = ApprovalRequest(
                action_id=f"{tool_name}_{method_name}",
                tool_name=tool_name,
                risk_level=risk,
                description=f"Action '{tool_name}.{method_name}' classified as {risk.value.upper()} risk.",
                params=params
            )

            # Path A: Explicit custom HITL callback
            if self.hitl_callback:
                approved = await self.hitl_callback(req)
                if not approved:
                    logger.warning(f"Action {tool_name}.{method_name} REJECTED by User HITL Approval Callback.")
                return approved

            # Path B: Integrated ApprovalStore async bridge
            if self.approval_store:
                logger.info(f"Action {tool_name}.{method_name} ({risk.value.upper()}) routing to ApprovalStore...")
                approval_id = self.approval_store.request(
                    task_id=task_id,
                    agent_id=agent_id or tool_name,
                    action=f"{tool_name}.{method_name}",
                    category=risk.value,
                    payload=params,
                    timeout=120.0
                )
                if self.task_event_bus:
                    try:
                        self.task_event_bus.publish({
                            "event": "APPROVAL_REQUIRED",
                            "status": "pending",
                            "approval_id": approval_id,
                            "tool_name": tool_name,
                            "method_name": method_name,
                            "risk_level": risk.value,
                            "params": params,
                            "task_id": task_id
                        })
                    except Exception as bus_err:
                        logger.warning(f"Failed to publish APPROVAL_REQUIRED event: {bus_err}")

                try:
                    from api.routes.websocket import notify_approval_pending
                    await notify_approval_pending(approval_id, f"{tool_name}.{method_name}")
                except Exception:
                    pass

                approved, reason = await self.approval_store.wait_for_approval(approval_id, timeout=120.0)
                if not approved:
                    logger.warning(f"Action {tool_name}.{method_name} REJECTED/EXPIRED in ApprovalStore: {reason}")
                return approved

            # Path C: Headless / Fail-Closed Fallback
            allow_headless = os.environ.get("JARVIS_ALLOW_HEADLESS_AUTO_APPROVE", "false").lower() == "true"
            if allow_headless:
                logger.warning(f"Action {tool_name}.{method_name} ({risk.value.upper()}) auto-approved because JARVIS_ALLOW_HEADLESS_AUTO_APPROVE=true.")
                return True

            logger.error(
                f"Action '{tool_name}.{method_name}' ({risk.value.upper()}) REJECTED: "
                "No HITL callback or ApprovalStore configured (FAIL-CLOSED SAFETY GATE)."
            )
            return False

        return True

