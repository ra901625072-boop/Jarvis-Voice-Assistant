"""
scheduler.py — Social Media Content Scheduler & Engagement Analytics Tracker.

Enables scheduling posts for future publication across LinkedIn and Instagram,
executing them via SocialMediaAgent, and tracking post metrics over time.
"""
import os
import json
import sqlite3
import logging
import uuid
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger("JARVIS.SocialScheduler")

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "scheduled_posts.db")


class SocialScheduler:
    """
    Manages scheduling queues and analytics tracking for social posts.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS scheduled_posts (
                        id TEXT PRIMARY KEY,
                        platform TEXT NOT NULL,
                        content TEXT NOT NULL,
                        media_path TEXT,
                        scheduled_time TEXT NOT NULL,
                        status TEXT DEFAULT 'pending',
                        post_id TEXT,
                        error TEXT,
                        analytics_json TEXT,
                        created_at TEXT NOT NULL,
                        published_at TEXT
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sched_time ON scheduled_posts(scheduled_time, status)")
        finally:
            conn.close()

    def schedule_post(
        self,
        platform: str,
        content: str,
        scheduled_time: str,
        media_path: Optional[str] = None
    ) -> str:
        sched_id = str(uuid.uuid4())
        now_str = datetime.now().isoformat()

        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO scheduled_posts (
                        id, platform, content, media_path, scheduled_time,
                        status, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """, (sched_id, platform.lower(), content, media_path, scheduled_time, now_str))
        finally:
            conn.close()

        logger.info(f"Scheduled social post ({sched_id}) for '{platform}' at {scheduled_time}.")
        return sched_id

    def list_scheduled_posts(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if status:
                cursor.execute("SELECT * FROM scheduled_posts WHERE status = ? ORDER BY scheduled_time ASC", (status,))
            else:
                cursor.execute("SELECT * FROM scheduled_posts ORDER BY scheduled_time ASC")
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def cancel_scheduled_post(self, sched_id: str) -> bool:
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE scheduled_posts SET status = 'cancelled' WHERE id = ? AND status = 'pending'", (sched_id,))
                return cursor.rowcount > 0
        finally:
            conn.close()

    async def check_and_publish_due_posts(self, social_media_agent) -> List[Dict[str, Any]]:
        """
        Queries all pending posts whose scheduled time is in the past,
        and dispatches them to SocialMediaAgent for publication.
        """
        now_str = datetime.now().isoformat()
        due_posts = []

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM scheduled_posts
                WHERE status = 'pending' AND scheduled_time <= ?
            """, (now_str,))
            due_posts = [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

        results = []
        for post in due_posts:
            post_id = post["id"]
            platform = post["platform"]
            content = post["content"]
            media = post["media_path"]

            logger.info(f"Executing scheduled post {post_id} on {platform}...")
            try:
                from ai.agents.types import AgentTask
                task = AgentTask(
                    task_type="post_content",
                    payload={"platform": platform, "content": content, "media_path": media}
                )
                res = await social_media_agent.handle(task)

                conn = self._get_connection()
                try:
                    with conn:
                        if res.success:
                            pub_at = datetime.now().isoformat()
                            ext_post_id = res.result.get("post_id", "published") if res.result else "published"
                            conn.execute("""
                                UPDATE scheduled_posts
                                SET status = 'published', published_at = ?, post_id = ?
                                WHERE id = ?
                            """, (pub_at, ext_post_id, post_id))
                            results.append({"id": post_id, "success": True, "platform": platform})
                        else:
                            conn.execute("""
                                UPDATE scheduled_posts
                                SET status = 'failed', error = ?
                                WHERE id = ?
                            """, (res.error, post_id))
                            results.append({"id": post_id, "success": False, "error": res.error})
                finally:
                    conn.close()
            except Exception as e:
                logger.exception(f"Failed publishing scheduled post {post_id}: {e}")
                results.append({"id": post_id, "success": False, "error": str(e)})

        return results

    def record_analytics(self, sched_id: str, analytics: Dict[str, Any]) -> bool:
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    UPDATE scheduled_posts
                    SET analytics_json = ?
                    WHERE id = ?
                """, (json.dumps(analytics), sched_id))
            return True
        finally:
            conn.close()
