import sqlite3, threading, uuid, time, os, json

class ApprovalStore:
    """
    Stores pending approvals and their resolution status.
    Agents block on wait_for_approval(); the API resolves them.
    """
    STATUS_PENDING  = "pending"
    STATUS_APPROVED = "approved"
    STATUS_DENIED   = "denied"
    STATUS_EXPIRED  = "expired"

    def __init__(self, db_path: str = None):
        if db_path is None:
            from config.settings import DATA_DIR
            db_path = os.path.join(DATA_DIR, "approvals.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._events: dict[str, threading.Event] = {}
        self._conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                task_id TEXT,
                agent_id TEXT,
                action TEXT,
                category TEXT,
                payload TEXT,
                status TEXT DEFAULT 'pending',
                reason TEXT,
                created_at REAL,
                resolved_at REAL
            );
        """)
        self._conn.commit()

    def request(self, task_id: str, agent_id: str, action: str,
                category: str, payload: dict, timeout: float = 120.0) -> str:
        approval_id = str(uuid.uuid4())[:12]
        with self._lock:
            self._conn.execute(
                "INSERT INTO approvals (approval_id, task_id, agent_id, action, category, payload, created_at) VALUES (?,?,?,?,?,?,?)",
                (approval_id, task_id, agent_id, action, category, json.dumps(payload), time.time())
            )
            self._conn.commit()
            self._events[approval_id] = threading.Event()
        return approval_id

    async def wait_for_approval(self, approval_id: str, timeout: float = 120.0) -> tuple[bool, str]:
        """Async-friendly wait. Returns (approved: bool, reason: str)."""
        import asyncio
        event = self._events.get(approval_id)
        if not event:
            return False, "Unknown approval ID"

        deadline = time.time() + timeout
        while time.time() < deadline:
            if event.is_set():
                row = self._conn.execute(
                    "SELECT status, reason FROM approvals WHERE approval_id=?", (approval_id,)
                ).fetchone()
                if row:
                    return row[0] == self.STATUS_APPROVED, row[1] or ""
                return False, "Resolution not found"
            await asyncio.sleep(0.5)

        # Expired
        with self._lock:
            self._conn.execute(
                "UPDATE approvals SET status=? WHERE approval_id=?",
                (self.STATUS_EXPIRED, approval_id)
            )
            self._conn.commit()
        return False, "Approval timed out"

    def resolve(self, approval_id: str, approved: bool, reason: str = "") -> bool:
        status = self.STATUS_APPROVED if approved else self.STATUS_DENIED
        with self._lock:
            self._conn.execute(
                "UPDATE approvals SET status=?, reason=?, resolved_at=? WHERE approval_id=?",
                (status, reason, time.time(), approval_id)
            )
            self._conn.commit()
            if approval_id in self._events:
                self._events[approval_id].set()
        return True

    def get_pending(self) -> list:
        rows = self._conn.execute(
            "SELECT * FROM approvals WHERE status='pending' ORDER BY created_at DESC"
        ).fetchall()
        cols = [c[0] for c in self._conn.execute("SELECT * FROM approvals LIMIT 0").description]
        return [dict(zip(cols, r)) for r in rows]
