import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("JARVIS.MemoryVision")

class MemoryVisionMixin:
    # ── Vision Cache & Memory (On-demand) ────────────────────────────────── #

    def get_cached_vision(self, image_hash: str, prompt: str) -> Optional[str]:
        """Retrieve cached vision output if it exists."""
        try:
            with self._lock.read_lock():
                cursor = self.dbs["conversations"].execute(
                    "SELECT result FROM vision_cache WHERE image_hash = ? AND prompt = ?",
                    (image_hash, prompt)
                )
                row = cursor.fetchone()
                if row:
                    return row[0]
        except Exception as e:
            logger.error(f"Failed to read from vision_cache: {e}")
        return None

    def set_cached_vision(self, image_hash: str, prompt: str, result: str) -> None:
        """Insert or replace a vision cache entry."""
        try:
            now = self._now()
            with self._lock.write_lock():
                self.dbs["conversations"].execute(
                    "INSERT OR REPLACE INTO vision_cache (image_hash, prompt, result, created_at) VALUES (?, ?, ?, ?)",
                    (image_hash, prompt, result, now)
                )
                self._commit()
        except Exception as e:
            logger.error(f"Failed to write to vision_cache: {e}")

    def save_vision_summary(self, app: str, activity: str, summary: str) -> None:
        """Save a summary of on-demand screen activity."""
        try:
            now = self._now()
            with self._lock.write_lock():
                self.dbs["conversations"].execute(
                    "INSERT INTO vision_memory (timestamp, app, activity, summary) VALUES (?, ?, ?, ?)",
                    (now, app, activity, summary)
                )
                self._commit()
        except Exception as e:
            logger.error(f"Failed to write to vision_memory: {e}")

    def get_recent_vision_summaries(self, limit: int = 5) -> list:
        """Retrieve recent vision summaries."""
        try:
            with self._lock.read_lock():
                cursor = self.dbs["conversations"].execute(
                    "SELECT timestamp, app, activity, summary FROM vision_memory ORDER BY id DESC LIMIT ?",
                    (limit,)
                )
                rows = cursor.fetchall()
            return [
                {"timestamp": r[0], "app": r[1], "activity": r[2], "summary": r[3]}
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get vision summaries: {e}")
            return []

    def cleanup_old_vision_logs(self, days: int = 30) -> None:
        """Prunes vision_memory and vision_cache tables of entries older than specified days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        try:
            with self._lock.write_lock():
                self.dbs["conversations"].execute(
                    "DELETE FROM vision_memory WHERE timestamp < ?",
                    (cutoff,),
                )
                self.dbs["conversations"].execute(
                    "DELETE FROM vision_cache WHERE created_at < ?",
                    (cutoff,),
                )
                self._commit(force=True)
            logger.info(f"Cleaned up vision logs and cache older than {days} days.")
        except Exception as e:
            logger.error(f"Failed to cleanup old vision logs: {e}")

    def query_lessons_learned(self, topic: str, limit: int = 3) -> list:
        """Query lessons learned from database in a thread-safe manner."""
        try:
            with self._lock.read_lock():
                if topic:
                    return self.dbs["conversations"].execute(
                        """SELECT lesson, occurrence_count 
                           FROM lessons_learned 
                           WHERE lesson LIKE ? OR source_pattern LIKE ?
                           ORDER BY importance DESC LIMIT ?""",
                        (f"%{topic}%", f"%{topic}%", limit)
                    ).fetchall()
                else:
                    return self.dbs["conversations"].execute(
                        """SELECT lesson, occurrence_count 
                           FROM lessons_learned 
                           ORDER BY importance DESC LIMIT ?""",
                        (limit,)
                    ).fetchall()
        except Exception as e:
            logger.error(f"Failed to query lessons_learned: {e}")
            return []
