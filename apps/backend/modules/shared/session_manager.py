import uuid
import time
import logging

logger = logging.getLogger("JARVIS.SessionManager")

class SessionManager:
    def __init__(self, memory):
        self.memory = memory
        self.current_session_id: str | None = None
        self.current_started_at: float | None = None

    def start_session(self, project: str = "general") -> str:
        self.current_session_id = str(uuid.uuid4())
        self.current_started_at = time.time()
        
        # Enqueue database write to create the session row
        self.memory.enqueue_write(
            self.memory._sync_create_session,
            self.current_session_id,
            self.memory._now(),  # ISO timestamp
            project
        )
        logger.info(f"Session started: {self.current_session_id}")
        return self.current_session_id

    def end_session(self, disconnect_reason: str) -> None:
        if not self.current_session_id:
            logger.warning("end_session called but no active session_id found.")
            return
        
        ended_at = self.memory._now()
        # Enqueue database write to close the session row
        self.memory.enqueue_write(
            self.memory._sync_close_session,
            self.current_session_id,
            ended_at,
            disconnect_reason
        )
        logger.info(f"Session ended: {self.current_session_id} (Reason: {disconnect_reason})")
