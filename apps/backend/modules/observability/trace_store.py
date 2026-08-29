import sqlite3, json, threading, time, os

class TraceStore:
    """
    Persists TraceSpan records to SQLite.
    Provides query methods for the dashboard API.
    """
    def __init__(self, db_path: str = None):
        if db_path is None:
            from config.settings import DATA_DIR
            db_path = os.path.join(DATA_DIR, "traces.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._lock = threading.Lock()
        
        from modules.shared.thread_local_db import ThreadLocalDBs
        self.dbs = ThreadLocalDBs(db_path)
        
        # Configure WAL on initialization connection
        conn = self.dbs.get_conn()
        conn.execute("PRAGMA journal_mode=WAL")
        
        self._init_schema()

    @property
    def _conn(self) -> sqlite3.Connection:
        return self.dbs.get_conn()

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS spans (
                span_id TEXT PRIMARY KEY,
                trace_id TEXT,
                agent_id TEXT,
                task_type TEXT,
                start_time REAL,
                duration_ms REAL,
                success INTEGER,
                tokens_used INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                confidence REAL DEFAULT 0.0,
                retries INTEGER DEFAULT 0,
                error TEXT,
                events TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
            CREATE INDEX IF NOT EXISTS idx_spans_agent ON spans(agent_id);
            CREATE INDEX IF NOT EXISTS idx_spans_created ON spans(created_at);
        """)
        self._conn.commit()

    def save(self, span) -> None:
        with self._lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO spans
                (span_id, trace_id, agent_id, task_type, start_time,
                 duration_ms, success, tokens_used, cost_usd, confidence,
                 retries, error, events)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                span.span_id, span.trace_id, span.agent_id, span.task_type,
                span.start_time, span.duration_ms, int(span.success or 0),
                span.tokens_used, span.cost_usd, span.confidence,
                span.retries, span.error,
                json.dumps([e.__dict__ for e in span.events])
            ))
            self._conn.commit()

    def start_async_writer(self, loop) -> None:
        """Starts the background worker task that consumes save operations from the queue."""
        if hasattr(self, "_writer_task") and self._writer_task and not self._writer_task.done():
            return
        import asyncio
        self._write_queue = asyncio.Queue()
        self._writer_task = loop.create_task(self._async_writer_loop())

    async def _async_writer_loop(self):
        import asyncio
        while True:
            try:
                span = await self._write_queue.get()
                await asyncio.to_thread(self.save, span)
                self._write_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                import logging
                logging.getLogger("JARVIS.TraceStore").error(f"Error in background trace writer loop: {e}")

    def enqueue_save(self, span) -> None:
        """Enqueues a save operation to be processed in the background, falling back to sync write if no loop exists."""
        if hasattr(self, "_write_queue"):
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(self._write_queue.put_nowait, span)
                return
            except RuntimeError:
                pass
        
        try:
            self.save(span)
        except Exception as e:
            import logging
            logging.getLogger("JARVIS.TraceStore").error(f"Fallback sync trace save failed: {e}")

    def get_recent(self, limit: int = 100) -> list:
        rows = self._conn.execute(
            "SELECT * FROM spans ORDER BY start_time DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(zip([c[0] for c in self._conn.execute("SELECT * FROM spans LIMIT 0").description], r)) for r in rows]

    def get_metrics(self) -> dict:
        row = self._conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successes,
                AVG(duration_ms) as avg_duration,
                SUM(tokens_used) as total_tokens,
                SUM(cost_usd) as total_cost,
                AVG(confidence) as avg_confidence
            FROM spans
            WHERE start_time > strftime('%s','now','-24 hours')
        """).fetchone()
        return {
            "total_tasks_24h": row[0],
            "success_rate_24h": round((row[1] / row[0] * 100) if row[0] else 0, 1),
            "avg_duration_ms": round(row[2] or 0, 1),
            "total_tokens_24h": row[3] or 0,
            "total_cost_usd_24h": round(row[4] or 0, 4),
            "avg_confidence": round(row[5] or 0, 2),
        }

    def get_agent_breakdown(self) -> list:
        rows = self._conn.execute("""
            SELECT agent_id,
                   COUNT(*) as runs,
                   AVG(CASE WHEN success=1 THEN 100.0 ELSE 0 END) as success_rate,
                   AVG(duration_ms) as avg_ms,
                   SUM(tokens_used) as tokens,
                   AVG(confidence) as avg_confidence
            FROM spans
            GROUP BY agent_id
            ORDER BY runs DESC
        """).fetchall()
        cols = ["agent_id", "runs", "success_rate", "avg_ms", "tokens", "avg_confidence"]
        return [dict(zip(cols, r)) for r in rows]
