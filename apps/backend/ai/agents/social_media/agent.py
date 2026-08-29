"""
agent.py — SocialMediaAgent (14th Agent) for Multi-Platform Social Media Orchestration.

Orchestrates read, summarize, draft, and action workflows across Gmail, WhatsApp,
LinkedIn, and Instagram with ApprovalEngine safety gates, CredentialVault integration,
ContactGraph identity resolution, PersonaStyleEngine tone matching, and SocialScheduler.
"""
import os
import uuid
import logging
import asyncio
from typing import Any, Dict, Optional, List

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult
from ai.agents.social_media.adapters.gmail_adapter import GmailAdapter
from ai.agents.social_media.adapters.whatsapp_adapter import WhatsAppAdapter
from ai.agents.social_media.adapters.linkedin_adapter import LinkedInAdapter
from ai.agents.social_media.adapters.instagram_adapter import InstagramAdapter

logger = logging.getLogger("JARVIS.SocialMediaAgent")


class SocialMediaAgent(BaseAgent):
    """
    SocialMediaAgent manages personal communications and social channels
    across Gmail, WhatsApp, LinkedIn, and Instagram.
    """

    SUPPORTED_PLATFORMS = ("gmail", "whatsapp", "linkedin", "instagram")

    SPECIALIST_TASK_MAP = {
        # WhatsApp Specialist Tasks
        "process_inbound_message": "whatsapp_agent",
        "notify_inbound_message": "whatsapp_agent",
        "inbound_message": "whatsapp_agent",
        "execute_business_tool": "whatsapp_agent",
        "get_agent_metrics": "whatsapp_agent",
        "toggle_auto_reply": "whatsapp_agent",
        "set_human_takeover": "whatsapp_agent",
        "list_escalations": "whatsapp_agent",
        # Gmail Specialist Tasks
        "triage_inbox": "gmail_agent",
        "triage_emails": "gmail_agent",
        "inbox_triage": "gmail_agent",
        "generate_draft": "gmail_agent",
        "create_contextual_draft": "gmail_agent",
        "review_drafts": "gmail_agent",
        "list_pending_drafts": "gmail_agent",
        "list_drafts": "gmail_agent",
        "approve_and_send_draft": "gmail_agent",
        "send_draft": "gmail_agent",
        "schedule_followup": "gmail_agent",
        "track_promise": "gmail_agent",
        "add_followup": "gmail_agent",
        "get_analytics": "gmail_agent",
        "get_inbox_analytics": "gmail_agent",
        "morning_briefing": "gmail_agent",
        "generate_morning_briefing": "gmail_agent",
        "toggle_auto_triage": "gmail_agent",
        "security_scan": "gmail_agent",
        # Instagram Specialist Tasks
        "research_trends": "instagram_agent",
        "trend_research": "instagram_agent",
        "instagram_research": "instagram_agent",
        "audit_competitor": "instagram_agent",
        "competitor_audit": "instagram_agent",
        "inspect_competitor": "instagram_agent",
        "generate_strategy": "instagram_agent",
        "create_strategy": "instagram_agent",
        "30day_strategy": "instagram_agent",
        "get_active_strategy": "instagram_agent",
        "view_strategy": "instagram_agent",
        "active_calendar": "instagram_agent",
        "create_content_brief": "instagram_agent",
        "generate_content": "instagram_agent",
        "create_reel_script": "instagram_agent",
        "create_post_brief": "instagram_agent",
        "create_carousel": "instagram_agent",
        "generate_carousel": "instagram_agent",
        "carousel_script": "instagram_agent",
        "validate_visuals": "instagram_agent",
        "check_safe_zones": "instagram_agent",
        "validate_aspect_ratio": "instagram_agent",
        "classify_comment": "instagram_agent",
        "triage_comment": "instagram_agent",
        "triage_comments": "instagram_agent",
        "qualify_dm_lead": "instagram_agent",
        "qualify_lead": "instagram_agent",
        "triage_dm": "instagram_agent",
        "list_leads": "instagram_agent",
        "get_dm_leads": "instagram_agent",
        "list_crm_leads": "instagram_agent",
        "analyze_post_performance": "instagram_agent",
        "analyze_post": "instagram_agent",
        "post_postmortem": "instagram_agent",
        "trigger_self_learning_cycle": "instagram_agent",
        "run_learning_cycle": "instagram_agent",
        "self_learn": "instagram_agent",
    }

    def __init__(
        self,
        bus,
        browser_controller=None,
        vision_agent=None,
        credential_vault=None,
        approval_engine=None,
        contact_graph=None,
        persona_style_engine=None,
        social_scheduler=None
    ):
        super().__init__(agent_id="social_media_agent")
        self.bus = bus
        self.browser = browser_controller
        self.vision = vision_agent
        self.vault = credential_vault
        self.approval = approval_engine
        self.contact_graph = contact_graph
        self.style_engine = persona_style_engine
        self.scheduler = social_scheduler

        # Initialize adapters
        self.adapters = {
            "gmail": GmailAdapter(credential_vault=self.vault),
            "whatsapp": WhatsAppAdapter(
                browser_controller=self.browser,
                vision_agent=self.vision,
                credential_vault=self.vault
            ),
            "linkedin": LinkedInAdapter(
                credential_vault=self.vault,
                browser_controller=self.browser,
                vision_agent=self.vision
            ),
            "instagram": InstagramAdapter(
                browser_controller=self.browser,
                vision_agent=self.vision,
                credential_vault=self.vault
            ),
        }

        if self.bus:
            self.bus.register(self.agent_id, self.handle)
        logger.info("SocialMediaAgent registered with Gmail, WhatsApp, LinkedIn, and Instagram adapters.")

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload or {}
        platform = str(payload.get("platform", "")).lower().strip()

        try:
            # ── Agent-wide cross-platform queries ─────────────────────────────
            if task_type in ("get_status", "health_check", "list_connections"):
                return await self._handle_get_status(task, payload)

            if task_type in ("social_digest", "read_all_inboxes"):
                return await self._handle_social_digest(task, payload)

            if task_type == "toggle_killswitch":
                return await self._handle_toggle_killswitch(task, payload)

            # ── Contact Graph operations ──────────────────────────────────────
            if task_type == "resolve_contact" and self.contact_graph:
                res = self.contact_graph.resolve_contact(payload.get("query", ""))
                return self._create_result(task, success=True, result={"contact": res})

            if task_type == "list_contacts" and self.contact_graph:
                res = self.contact_graph.list_contacts(payload.get("limit", 50))
                return self._create_result(task, success=True, result={"contacts": res})

            if task_type == "link_identity" and self.contact_graph:
                res = self.contact_graph.link_identity(
                    payload.get("contact_id", ""),
                    payload.get("platform", ""),
                    payload.get("identifier", "")
                )
                return self._create_result(task, success=res, result={"linked": res})

            # ── Scheduling operations ─────────────────────────────────────────
            if task_type == "schedule_post" and self.scheduler:
                sched_id = self.scheduler.schedule_post(
                    platform=payload.get("platform", "linkedin"),
                    content=payload.get("content", ""),
                    scheduled_time=payload.get("scheduled_time", ""),
                    media_path=payload.get("media_path")
                )
                return self._create_result(task, success=True, result={"scheduled_id": sched_id})

            if task_type == "list_scheduled_posts" and self.scheduler:
                posts = self.scheduler.list_scheduled_posts(payload.get("status"))
                return self._create_result(task, success=True, result={"scheduled_posts": posts})

            # ── Persona Style Drafting ────────────────────────────────────────
            if task_type in ("generate_personalized_reply", "draft_personalized_reply"):
                return await self._handle_personalized_draft(task, payload)

            # ── Delegate to Specialist Vertical Agent if applicable ──────────
            target_specialist = self.SPECIALIST_TASK_MAP.get(task_type)
            if target_specialist and self.bus and hasattr(self.bus, "_handlers") and target_specialist in self.bus._handlers:
                forwarded_task = AgentTask(
                    task_id=getattr(task, "task_id", "") or str(uuid.uuid4()),
                    task_type=task_type,
                    payload=payload,
                    origin_agent=self.agent_id,
                    target_agent=target_specialist,
                    dispatch_chain=getattr(task, "dispatch_chain", []) + [self.agent_id]
                )
                return await self.bus.dispatch(forwarded_task)

            # ── Single platform validation ────────────────────────────────────
            if not platform or platform not in self.adapters:
                return self._create_result(
                    task,
                    success=False,
                    error=f"Unsupported or missing platform '{platform}'. Supported: {list(self.adapters.keys())}"
                )

            adapter = self.adapters[platform]

            # Check killswitch in vault or adapter
            is_paused = False
            if self.vault and hasattr(self.vault, "is_killswitch_active"):
                is_paused = self.vault.is_killswitch_active(platform)
            if not is_paused and hasattr(adapter, "is_killswitch_active"):
                is_paused = adapter.is_killswitch_active()

            if is_paused:
                return self._create_result(
                    task,
                    success=False,
                    error=f"Platform '{platform}' is currently paused via kill switch."
                )

            # ── Account Connection / Disconnection ────────────────────────────
            if task_type == "connect_account":
                ok = await adapter.connect(**payload)
                return self._create_result(task, success=ok, result={"platform": platform, "connected": ok})

            if task_type == "disconnect_account":
                ok = await adapter.disconnect()
                return self._create_result(task, success=ok, result={"platform": platform, "disconnected": ok})

            # ── Safety & Approval Gate ────────────────────────────────────────
            auto_approve = (
                os.environ.get("JARVIS_AUTO_APPROVE_SOCIAL", "false").lower() == "true"
                or os.environ.get("JARVIS_AUTO_APPROVE", "false").lower() == "true"
                or os.environ.get("JARVIS_AUTO_CONFIRM", "false").lower() == "true"
            )

            if not payload.get("bypass_approval") and not auto_approve and self.approval:
                preview_data = adapter.get_approval_preview(task_type, payload)
                combined_params = {**payload, "platform": platform, "approval_preview": preview_data}
                task_id = getattr(task, "id", "") or getattr(task, "correlation_id", "")
                
                approved = await self.approval.authorize(
                    tool_name="social_media",
                    method_name=task_type,
                    params=combined_params,
                    task_id=task_id,
                    agent_id="social_media_agent"
                )
                if not approved:
                    return self._create_result(
                        task,
                        success=False,
                        error=f"Action '{task_type}' on {platform} was rejected or timed out awaiting human approval."
                    )

            # ── Delegate to Platform Adapter ──────────────────────────────────
            execution_res = await adapter.execute(task_type, payload)
            success = execution_res.get("success", True)
            error = execution_res.get("error")
            return self._create_result(task, success=success, result=execution_res, error=error)

        except Exception as e:
            logger.exception(f"SocialMediaAgent encountered unexpected exception on '{task_type}'")
            return self._create_result(task, success=False, error=str(e))

    async def _handle_personalized_draft(self, task: AgentTask, payload: Dict[str, Any]) -> AgentResult:
        platform = payload.get("platform", "gmail").lower()
        recipient_str = payload.get("to") or payload.get("recipient") or payload.get("contact", "")
        raw_body = payload.get("body") or payload.get("text") or payload.get("draft", "")

        relationship = "contact"
        recipient_name = recipient_str
        if self.contact_graph and recipient_str:
            c = self.contact_graph.resolve_contact(recipient_str)
            if c:
                relationship = c.get("relationship", "contact")
                recipient_name = c.get("full_name") or recipient_str

        formatted_draft = raw_body
        if self.style_engine:
            formatted_draft = self.style_engine.format_draft(
                platform=platform,
                content=raw_body,
                recipient_name=recipient_name
            )

        return self._create_result(task, success=True, result={
            "platform": platform,
            "recipient": recipient_name,
            "relationship": relationship,
            "draft": formatted_draft
        })

    async def _handle_get_status(self, task: AgentTask, payload: Dict[str, Any]) -> AgentResult:
        statuses = {}
        for name, adapter in self.adapters.items():
            h = await adapter.health()
            statuses[name] = h
        return self._create_result(task, success=True, result={"platforms": statuses})

    async def _handle_social_digest(self, task: AgentTask, payload: Dict[str, Any]) -> AgentResult:
        """Fetch unified inbox items from all connected platforms concurrently."""
        limit_per_platform = payload.get("limit_per_platform", 5)
        results = {}

        async def fetch_platform(name, adapter):
            try:
                h = await adapter.health()
                if h.get("connected"):
                    res = await adapter.execute("read_inbox", {"limit": limit_per_platform})
                    return name, res
                return name, {"connected": False, "status": "Not connected"}
            except Exception as e:
                return name, {"success": False, "error": str(e)}

        tasks = [fetch_platform(name, ad) for name, ad in self.adapters.items()]
        gathered = await asyncio.gather(*tasks)
        for name, res in gathered:
            results[name] = res

        return self._create_result(task, success=True, result={"social_digest": results})

    async def _handle_toggle_killswitch(self, task: AgentTask, payload: Dict[str, Any]) -> AgentResult:
        platform = payload.get("platform", "").lower().strip()
        enabled = payload.get("enabled", True)
        if platform not in self.adapters:
            return self._create_result(task, success=False, error=f"Unknown platform '{platform}'")

        self.adapters[platform].set_killswitch(enabled)
        if self.vault:
            self.vault.set_killswitch(platform, enabled)

        return self._create_result(
            task,
            success=True,
            result={"platform": platform, "killswitch": enabled, "message": f"Killswitch set to {enabled}"}
        )
