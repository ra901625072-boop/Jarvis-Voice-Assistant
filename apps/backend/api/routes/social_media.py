import os
import sqlite3
import json
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from typing import Dict, Any, Optional
from ai.agents.types import AgentTask

from api.middleware.auth import get_current_user

router = APIRouter(prefix="/api/social", tags=["Social Media"])


def get_container():
    from container import ServiceContainer
    return ServiceContainer.instance()


def get_vault():
    container = get_container()
    if container:
        return container.get_or_none("credential_vault")
    from modules.security.credential_vault import CredentialVault
    return CredentialVault()


def get_agent():
    container = get_container()
    if container:
        agent = container.get_or_none("social_media_agent")
        if agent:
            return agent
    try:
        from ai.agents.social_media.agent import SocialMediaAgent
        from modules.controls.browser_controller import BrowserController
        return SocialMediaAgent(bus=None, browser_controller=BrowserController())
    except Exception:
        return None


def get_contact_graph():
    container = get_container()
    if container:
        return container.get_or_none("contact_graph")
    from modules.social.contact_graph import ContactGraphManager
    return ContactGraphManager()


def get_persona_engine():
    container = get_container()
    if container:
        return container.get_or_none("persona_style_engine")
    from modules.social.persona_style_engine import PersonaStyleEngine
    return PersonaStyleEngine()


def get_social_scheduler():
    container = get_container()
    if container:
        return container.get_or_none("social_scheduler")
    from modules.social.scheduler import SocialScheduler
    return SocialScheduler()


# ── Connections & Killswitch ──────────────────────────────────────────────────

@router.get("/connections")
async def get_connections(
    current_user=Depends(get_current_user),
    vault=Depends(get_vault),
    agent=Depends(get_agent)
):
    """Return status of all configured social media platforms and rate limits."""
    vault_statuses = vault.get_all_statuses() if vault else {}
    if agent:
        for platform_name, adapter in agent.adapters.items():
            try:
                h = await adapter.health()
                if platform_name in vault_statuses:
                    vault_statuses[platform_name]["live_health"] = h
                    vault_statuses[platform_name]["rate_limit"] = await adapter.get_rate_limit_status()
            except Exception:
                pass
    return {"connections": vault_statuses}


@router.post("/connect/{platform}")
async def connect_platform(
    platform: str,
    body: Dict[str, Any] = Body(...),
    current_user=Depends(get_current_user),
    vault=Depends(get_vault),
    agent=Depends(get_agent)
):
    """Store credentials or tokens for a platform."""
    platform_norm = platform.lower().strip()
    if platform_norm not in ("gmail", "whatsapp", "linkedin", "instagram"):
        raise HTTPException(400, f"Unsupported platform: {platform}")

    cred_type = body.get("type", "oauth" if platform_norm in ("gmail", "linkedin") else "session")
    tokens = body.get("tokens") or body.get("credentials") or body

    if cred_type == "oauth":
        ok = vault.store_oauth_tokens(platform_norm, tokens, meta={"source": "api_connect"})
    else:
        ok = vault.store_session_state(platform_norm, tokens, meta={"source": "api_connect"})

    if not ok:
        raise HTTPException(500, f"Failed to store credentials for {platform_norm}")

    connected = False
    if agent and platform_norm in agent.adapters:
        try:
            connected = await agent.adapters[platform_norm].connect()
        except Exception:
            connected = False

    return {
        "status": "success",
        "platform": platform_norm,
        "connected": connected,
        "vault_stored": True
    }


@router.post("/disconnect/{platform}")
async def disconnect_platform(
    platform: str,
    current_user=Depends(get_current_user),
    vault=Depends(get_vault),
    agent=Depends(get_agent)
):
    """Revoke credentials and disconnect platform."""
    platform_norm = platform.lower().strip()
    if vault:
        vault.revoke(platform_norm)
    if agent and platform_norm in agent.adapters:
        await agent.adapters[platform_norm].disconnect()
    return {"status": "disconnected", "platform": platform_norm}


@router.post("/toggle-killswitch/{platform}")
async def toggle_killswitch(
    platform: str,
    body: Dict[str, Any] = Body(default={"enabled": True}),
    current_user=Depends(get_current_user),
    vault=Depends(get_vault),
    agent=Depends(get_agent)
):
    """Enable or disable emergency kill switch for a specific platform."""
    platform_norm = platform.lower().strip()
    enabled = body.get("enabled", True)
    if vault:
        vault.set_killswitch(platform_norm, enabled)
    if agent and platform_norm in agent.adapters:
        agent.adapters[platform_norm].set_killswitch(enabled)
    return {"status": "success", "platform": platform_norm, "killswitch": enabled}


@router.post("/action")
async def execute_social_action(
    body: Dict[str, Any] = Body(...),
    current_user=Depends(get_current_user),
    agent=Depends(get_agent)
):
    """Direct invocation endpoint for social actions."""
    if not agent:
        raise HTTPException(503, "SocialMediaAgent is not initialized")

    from ai.agents.types import AgentTask
    task_type = body.get("task_type", "read_inbox")
    payload = body.get("payload", body)

    task = AgentTask(task_type=task_type, payload=payload, origin_agent="api")
    result = await agent.handle(task)
    return result.to_dict()


# ── Contact Graph Endpoints ───────────────────────────────────────────────────

@router.get("/contacts")
async def list_contacts(
    limit: int = Query(50, ge=1, le=200),
    contact_graph=Depends(get_contact_graph),
    current_user=Depends(get_current_user)
):
    """Returns list of contacts in unified ContactGraph."""
    return {"contacts": contact_graph.list_contacts(limit=limit)}


@router.post("/contacts")
async def add_or_update_contact(
    body: Dict[str, Any] = Body(...),
    contact_graph=Depends(get_contact_graph),
    current_user=Depends(get_current_user)
):
    """Add or update a unified contact entity."""
    c_id = contact_graph.add_or_update_contact(body)
    return {"status": "success", "contact_id": c_id}


@router.get("/contacts/resolve")
async def resolve_contact(
    query: str = Query(..., min_length=1),
    contact_graph=Depends(get_contact_graph),
    current_user=Depends(get_current_user)
):
    """Fuzzy resolves a contact by name, email, phone, or handle."""
    res = contact_graph.resolve_contact(query)
    if not res:
        raise HTTPException(404, f"No contact matched query '{query}'")
    return {"contact": res}


@router.post("/contacts/{contact_id}/link")
async def link_identity(
    contact_id: str,
    platform: str = Body(..., embed=True),
    identifier: str = Body(..., embed=True),
    contact_graph=Depends(get_contact_graph),
    current_user=Depends(get_current_user)
):
    """Link a platform account (e.g. whatsapp phone, instagram handle) to a contact."""
    ok = contact_graph.link_identity(contact_id, platform, identifier)
    return {"status": "success" if ok else "failed", "linked": ok}


# ── Post Scheduling Endpoints ─────────────────────────────────────────────────

@router.get("/schedule")
async def list_scheduled_posts(
    status: Optional[str] = Query(None),
    scheduler=Depends(get_social_scheduler),
    current_user=Depends(get_current_user)
):
    """List scheduled social posts."""
    posts = scheduler.list_scheduled_posts(status=status)
    return {"scheduled_posts": posts}


@router.post("/schedule")
async def create_scheduled_post(
    body: Dict[str, Any] = Body(...),
    scheduler=Depends(get_social_scheduler),
    current_user=Depends(get_current_user)
):
    """Schedule a post for LinkedIn or Instagram."""
    sched_id = scheduler.schedule_post(
        platform=body.get("platform", "linkedin"),
        content=body.get("content", ""),
        scheduled_time=body.get("scheduled_time", ""),
        media_path=body.get("media_path")
    )
    return {"status": "scheduled", "id": sched_id}


@router.delete("/schedule/{sched_id}")
async def cancel_scheduled_post(
    sched_id: str,
    scheduler=Depends(get_social_scheduler),
    current_user=Depends(get_current_user)
):
    """Cancel a scheduled post."""
    ok = scheduler.cancel_scheduled_post(sched_id)
    return {"status": "cancelled" if ok else "not_found", "success": ok}


# ── Persona Style Endpoints ───────────────────────────────────────────────────

@router.get("/persona/{platform}")
async def get_persona_profile(
    platform: str,
    persona_engine=Depends(get_persona_engine),
    current_user=Depends(get_current_user)
):
    """Get tone and style guidelines for a platform."""
    return {"platform": platform, "profile": persona_engine.get_style_profile(platform)}


@router.post("/persona/{platform}")
async def update_persona_profile(
    platform: str,
    body: Dict[str, Any] = Body(...),
    persona_engine=Depends(get_persona_engine),
    current_user=Depends(get_current_user)
):
    """Update style profile preferences for a platform."""
    persona_engine.update_style_profile(platform, body)
    return {"status": "success", "platform": platform, "updated_profile": persona_engine.get_style_profile(platform)}


# ── Persistent HIPL Pending Approvals ─────────────────────────────────────────

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "contacts.db"))



@router.get("/approvals")
async def list_pending_approvals(current_user=Depends(get_current_user)):
    """List all pending social media actions awaiting user approval."""
    approvals = []
    try:
        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:

            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_approvals (
                    id TEXT PRIMARY KEY,
                    platform TEXT,
                    task_type TEXT,
                    payload TEXT,
                    correlation_id TEXT,
                    timestamp TEXT,
                    status TEXT
                )
            """)
            cursor.execute("SELECT * FROM pending_approvals WHERE status = 'PENDING' ORDER BY timestamp DESC")
            rows = cursor.fetchall()
            for r in rows:
                approvals.append({
                    "id": r["id"],
                    "platform": r["platform"],
                    "task_type": r["task_type"],
                    "payload": json.loads(r["payload"]),
                    "correlation_id": r["correlation_id"],
                    "timestamp": r["timestamp"]
                })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query pending approvals: {str(e)}")
    return {"pending_approvals": approvals}


@router.post("/approve/{task_db_id}")
async def approve_pending_task(
    task_db_id: str,
    agent=Depends(get_agent),
    current_user=Depends(get_current_user)
):
    """Approve and execute a pending social media action."""
    if not agent:
        raise HTTPException(status_code=500, detail="SocialMediaAgent is not initialized")

    task_data = None
    try:
        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM pending_approvals WHERE id = ? AND status = 'PENDING'", (task_db_id,))
            row = cursor.fetchone()
            if row:
                task_data = dict(row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error reading task: {str(e)}")

    if not task_data:
        raise HTTPException(status_code=404, detail="Pending approval task not found")

    payload = json.loads(task_data["payload"])
    payload["bypass_approval"] = True  # Tell the agent to skip safety gate and execute directly

    task = AgentTask(
        task_type=task_data["task_type"],
        payload=payload
    )

    result = await agent.handle(task)

    if result.success:
        try:
            with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
                conn.execute("UPDATE pending_approvals SET status = 'APPROVED' WHERE id = ?", (task_db_id,))
        except Exception:
            pass
        return {"status": "success", "message": "Task approved and executed", "result": result.result}
    else:
        return {"status": "failed", "error": result.error, "message": "Failed executing approved task"}


@router.post("/reject/{task_db_id}")
async def reject_pending_task(
    task_db_id: str,
    current_user=Depends(get_current_user)
):
    """Reject and cancel a pending social media action."""
    try:
        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM pending_approvals WHERE id = ? AND status = 'PENDING'", (task_db_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Pending approval task not found")
            conn.execute("UPDATE pending_approvals SET status = 'REJECTED' WHERE id = ?", (task_db_id,))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error rejecting task: {str(e)}")

    return {"status": "success", "message": "Task rejected"}

