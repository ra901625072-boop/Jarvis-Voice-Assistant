from fastapi import APIRouter, Depends, HTTPException
from api.middleware.auth import get_current_user, require_role

router = APIRouter(prefix="/api/approvals", tags=["Approvals"])

def get_approval_store():
    from container import ServiceContainer
    c = ServiceContainer.instance()
    if c:
        store = c.get_or_none("approval_store")
        if store:
            return store
    from modules.approval.approval_store import ApprovalStore
    return ApprovalStore()

@router.get("")
async def list_pending(current_user=Depends(get_current_user), store=Depends(get_approval_store)):
    import json
    pending = store.get_pending()
    mapped = []
    for app in pending:
        payload_obj = {}
        if app.get("payload"):
            try:
                payload_obj = json.loads(app["payload"])
            except Exception:
                payload_obj = app["payload"]
        
        mapped.append({
            "id": app.get("approval_id"),
            "action": app.get("action"),
            "details": payload_obj,
            "message": f"Action '{app.get('action')}' requires approval."
        })
    return {"approvals": mapped}

@router.post("/{approval_id}/approve")
async def approve(approval_id: str, body: dict = None,
                  current_user=Depends(require_role(["admin"])),
                  store=Depends(get_approval_store)):
    body = body or {}
    ok = store.resolve(approval_id, approved=True, reason=body.get("reason", ""))
    if not ok:
        raise HTTPException(404, "Approval not found")
    return {"status": "approved"}

@router.post("/{approval_id}/deny")
async def deny(approval_id: str, body: dict = None,
               current_user=Depends(require_role(["admin"])),
               store=Depends(get_approval_store)):
    body = body or {}
    ok = store.resolve(approval_id, approved=False, reason=body.get("reason", "Denied by user"))
    if not ok:
        raise HTTPException(404, "Approval not found")
    return {"status": "denied"}
