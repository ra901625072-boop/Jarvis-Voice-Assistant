import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("JARVIS.PromptPatchManager")

class PromptPatchManager:
    def __init__(self, learning_orchestrator):
        self.orchestrator = learning_orchestrator

    def propose_patch(self, agent_id: str, issue: str, original_prompt_snippet: str, recommended_patch: str, reason: Optional[str] = None, source_event_id: Optional[int] = None) -> int:
        payload = {
            "agent_id": agent_id,
            "issue": issue,
            "original_prompt_snippet": original_prompt_snippet,
            "recommended_patch": recommended_patch,
            "reason": reason
        }
        return self.orchestrator.create_recommendation(
            source_event_id=source_event_id,
            target_agent=agent_id,
            recommendation_type="prompt_patch",
            payload=payload
        )

    def get_pending_patches(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        recs = self.orchestrator.get_pending_recommendations(target_agent=agent_id)
        return [r for r in recs if r["recommendation_type"] == "prompt_patch"]

    def apply_patch_with_audit(self, recommendation_id: int, original_prompt_text: str, patched_prompt_text: str, notes: Optional[str] = None) -> int:
        """
        Log the prompt patch to the audit log, update its status, and return the audit ID.
        """
        self.orchestrator.update_recommendation_status(recommendation_id, "resolved")
        audit_id = self.orchestrator.log_audit_trail(
            change_type="prompt_patch",
            before_state=original_prompt_text,
            after_state=patched_prompt_text,
            recommendation_id=recommendation_id,
            notes=notes or "Applied proposed system prompt patch.",
            status="applied"
        )
        logger.info(f"PromptPatchManager: Applied prompt patch (recommendation #{recommendation_id}), logged in audit trail #{audit_id}.")
        return audit_id

    def rollback_patch(self, audit_id: int) -> int:
        """
        Reverts a prompt patch by retrieving the before_state from the audit logs and registering a rollback trail.
        """
        # Find the original audit log entry
        with self.orchestrator.mm._lock:
            row = self.orchestrator._dbs["conversations"].execute(
                """SELECT change_type, before_state, after_state, recommendation_id, notes
                   FROM learning_audit_log WHERE id = ?""",
                (audit_id,)
            ).fetchone()
            
            if not row:
                raise ValueError(f"PromptPatchManager: Audit log with id {audit_id} not found.")

            change_type, before_state, after_state, rec_id, original_notes = row

            # Insert rollback audit log entry
            new_audit_id = self.orchestrator.log_audit_trail(
                change_type="prompt_rollback",
                before_state=after_state,
                after_state=before_state,
                recommendation_id=rec_id,
                status="rolled_back",
                rollback_pointer=audit_id,
                notes=f"Reverted patch from audit #{audit_id}. Original notes: {original_notes}"
            )
            
            # Re-open original recommendation if applicable
            if rec_id:
                self.orchestrator.update_recommendation_status(rec_id, "pending")

        logger.info(f"PromptPatchManager: Reverted prompt patch #{audit_id}, registered rollback trail #{new_audit_id}.")
        return new_audit_id
