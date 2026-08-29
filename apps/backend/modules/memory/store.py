import os
import time
import logging
import shutil
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from modules.memory.scorer import MemoryImportance

logger = logging.getLogger("JARVIS.MemoryStore")

class MemoryStoreMixin:
    # ── Conversation logging ──────────────────────────────────────────── #

    def log_conversation(self, role: str, content: str, session_id: str = None) -> None:
        """Log a conversation turn. Offloaded to background queue to prevent event loop delay."""
        timestamp = self._now()
        meta = self._scorer.analyze(content, role)
        self.enqueue_write(self._sync_log_conversation, role, content, timestamp, meta, session_id)

    def _sync_log_conversation(self, role: str, content: str, timestamp: str, meta: dict, session_id: str = None) -> None:
        importance   = meta["importance"]
        memory_type  = meta["memory_type"]
        project      = meta["project"]
        tags         = meta["tags"]

        # Always write to the raw conversations table (full audit log)
        with self._lock.write_lock():
            cursor = self.dbs["conversations"].execute(
                """INSERT INTO conversations
                   (timestamp, role, content, importance, memory_type, project, session_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (timestamp, role, content, importance, memory_type, project, session_id),
            )
            inserted_id = cursor.lastrowid
            
            # Increment turn count in sessions table if session_id is provided
            if session_id:
                self.dbs["conversations"].execute(
                    "UPDATE sessions SET turn_count = turn_count + 1 WHERE session_id = ?",
                    (session_id,)
                )
            self._commit()

        # Phase 5: route through memory lifecycle (gate + resolve + store)
        _FAST_CHAT_MODE = os.getenv("JARVIS_FAST_CHAT", "1") == "1"
        if _FAST_CHAT_MODE and importance < MemoryImportance.MEDIUM:
            stored = False
        else:
            try:
                stored = self.lifecycle.on_new_message(
                    content=content,
                    role=role,
                    importance=importance,
                    memory_type=memory_type,
                    project=project,
                    tags=tags,
                    timestamp=timestamp,
                )
            except Exception as e:
                logger.error(f"Lifecycle on_new_message failed, falling back: {e}")
                stored = False
                if importance >= MemoryImportance.MEDIUM:
                    self._store_typed_memory(content, memory_type, project, importance, tags, timestamp)
                    stored = True

        # Vector store with rich metadata (only if important enough)
        if importance >= MemoryImportance.MEDIUM and self._ensure_vector_client():
            try:
                self.collection.add(
                    documents=[content],
                    metadatas=[{
                        "role":        role,
                        "importance":  meta["importance"],
                        "memory_type": meta["memory_type"],
                        "project":     meta["project"],
                        "tags":        meta["tags"],
                        "timestamp":   timestamp,
                    }],
                    ids=[str(inserted_id)],
                )
            except Exception as e:
                logger.error(f"Vector insert failed: {e}")

    def get_recent_history(self, limit: int = 10) -> list:
        with self._lock.read_lock():
            cursor = self.dbs["conversations"].execute(
                "SELECT role, content FROM conversations ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            results = cursor.fetchall()
        return [{"role": r[0], "content": r[1]} for r in reversed(results)]

    def search_history(self, query: str, limit: int = 5) -> list:
        """Hybrid retrieval: vector similarity + importance + recency."""
        return self._hybrid_search(query, collection=self.collection, limit=limit)

    def get_full_context(self, current_query: str = None, project_name: str = None) -> str:
        """
        Builds a comprehensive context string for the LLM prompt.
        Phase 5: Delegates to MemoryLifecycle.build_context() which:
          - Applies a token budget (default 3000 tokens)
          - Prioritises: goals > preferences > tasks > memories > KG > lessons > reflections
          - Includes goal-relevance scores and agent self-model
        """
        try:
            return self.lifecycle.build_context(current_query=current_query, project_name=project_name)
        except Exception as e:
            logger.error(f"Lifecycle context build failed, using fallback: {e}")
            # Fallback to basic context
            parts = []
            prefs = self.get_all_preferences()
            if prefs:
                parts.append("--- USER PREFERENCES ---\n" + "\n".join(f"- {k}: {v}" for k, v in prefs.items()))
            return "\n\n".join(parts)

    # ── Workflow memory ───────────────────────────────────────────────── #

    def save_workflow(self, goal: str, subtasks: list) -> None:
        """Save a successful workflow plan to vector DB."""
        if not self._ensure_vector_client():
            return
        try:
            workflow_id = f"wf_{int(time.time())}"
            content = f"Goal: {goal}\nSteps:\n" + "\n".join(f"- {t}" for t in subtasks)
            self.workflow_collection.add(
                documents=[content],
                metadatas=[{"goal": goal, "timestamp": self._now()}],
                ids=[workflow_id],
            )
            logger.info(f"Workflow saved: '{goal}'")
        except Exception as e:
            logger.error(f"Failed to save workflow: {e}")

    def search_workflows(self, query: str, limit: int = 3) -> list:
        """Search past successful plans."""
        if not self._ensure_vector_client():
            return []
        try:
            res = self.workflow_collection.query(query_texts=[query], n_results=limit)
            if res and res["documents"] and res["documents"][0]:
                return [
                    {"goal": m["goal"], "plan": d}
                    for d, m in zip(res["documents"][0], res["metadatas"][0])
                ]
        except Exception as e:
            logger.error(f"Workflow search failed: {e}")
        return []

    # ── Preferences ───────────────────────────────────────────────────── #

    def set_preference(self, key: str, value: str) -> None:
        if not hasattr(self, "_pref_cache"):
            self._pref_cache = {}
        self._pref_cache[key] = value
        with self._lock.write_lock():
            self.dbs["user"].execute(
                "INSERT OR REPLACE INTO preferences (key, value) VALUES (?, ?)", (key, value)
            )
            self.dbs["user"].commit()
        # Mirror important preferences to semantic memory (dedup by key)
        content = f"User preference: {key} = {value}"
        importance = MemoryImportance.HIGH
        with self._lock.write_lock():
            # Remove previous version of this preference from semantic memory
            self.dbs["user"].execute(
                "DELETE FROM semantic_memories WHERE tags = 'preference' AND content LIKE ?",
                (f"User preference: {key} =%",),
            )
            self.dbs["user"].execute(
                """INSERT INTO semantic_memories
                   (content, importance, project, tags, decay_score, created_at, updated_at)
                   VALUES (?, ?, 'general', 'preference', 1.0, ?, ?)""",
                (content, importance, self._now(), self._now()),
            )
            self._commit()

    def get_preference(self, key: str, default=None):
        if not hasattr(self, "_pref_cache"):
            self._pref_cache = {}
        if key in self._pref_cache:
            return self._pref_cache[key]
        with self._lock.read_lock():
            cursor = self.dbs["user"].execute(
                "SELECT value FROM preferences WHERE key = ?", (key,)
            )
            result = cursor.fetchone()
        val = result[0] if result else default
        self._pref_cache[key] = val
        return val

    def get_all_preferences(self) -> dict:
        with self._lock.read_lock():
            cursor = self.dbs["user"].execute("SELECT key, value FROM preferences")
            results = cursor.fetchall()
        prefs = {k: v for k, v in results}
        self._pref_cache = dict(prefs)
        return prefs

    def delete_preference(self, key: str) -> bool:
        if hasattr(self, "_pref_cache") and key in self._pref_cache:
            del self._pref_cache[key]
        with self._lock.write_lock():
            cursor = self.dbs["user"].execute(
                "DELETE FROM preferences WHERE key = ?", (key,)
            )
            self.dbs["user"].commit()
            return cursor.rowcount > 0

    # ── Maintenance ───────────────────────────────────────────────────── #

    def prune_old_conversations(self, days: int = 90) -> None:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._lock.write_lock():
            cursor = self.dbs["conversations"].execute(
                "DELETE FROM conversations WHERE timestamp < ?", (cutoff,)
            )
            self.dbs["conversations"].commit()
            logger.info(f"Pruned {cursor.rowcount} old conversations.")

    def log_session_disconnect(self, duration: float, disconnect_reason: str) -> None:
        try:
            with self._lock.write_lock():
                conn = self.dbs.get_conn()
                conn.execute(
                    "INSERT INTO session_metrics (timestamp, duration, disconnect_reason) VALUES (?, ?, ?)",
                    (self._now(), duration, disconnect_reason)
                )
                self._commit(force=True)
        except Exception as e:
            import logging
            logging.getLogger("JARVIS.Memory").error(f"Failed to log session disconnect: {e}")

    def backup_databases(self) -> None:
        logger.info("Running automated database backup...")
        with self._lock.write_lock():
            conn = self.dbs.get_conn()
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception as e:
                logger.warning(f"Failed to run WAL checkpoint before backup: {e}")
            conn.commit()
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            src = os.path.join(self.memory_dir, "memory.db")
            dst = os.path.join(self.backup_dir, f"memory_{ts}.bak")
            if os.path.exists(src):
                shutil.copy2(src, dst)
        logger.info("Database backup complete.")

    def clear_history(self) -> None:
        with self._lock.write_lock():
            self.dbs["conversations"].execute("DELETE FROM conversations")
            self.dbs["conversations"].commit()
            if self._ensure_vector_client():
                try:
                    self.chroma_client.delete_collection("conversations")
                    self.collection = self.chroma_client.create_collection("conversations")
                except Exception as e:
                    logger.debug(f"ChromaDB reset: {e}")

    def run_nightly_maintenance(self) -> None:
        """Delegates to MemoryLifecycle.run_nightly() for full maintenance pipeline."""
        logger.info("Triggering nightly maintenance via MemoryLifecycle...")
        try:
            self.lifecycle.run_nightly()
            
            # Force WAL checkpoint to reclaim space only if successful
            with self._lock.write_lock():
                conn = self.dbs.get_conn()
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.commit()
            logger.info("WAL checkpoint completed.")
        except Exception as e:
            logger.error(f"Nightly maintenance error: {e}", exc_info=True)

    def close(self) -> None:
        if hasattr(self, "_stop_event"):
            self._stop_event.set()
        with self._lock.write_lock():
            self.dbs.commit_all_and_close()
        logger.info("MemoryManager closed.")

    # ── Typed memory storage ──────────────────────────────────────────── #

    def store_memory(
        self,
        content: str,
        memory_type: str = "semantic",
        project: str = "general",
        importance: int = None,
        tags: str = None,
    ) -> int:
        """
        Explicitly store a memory entry.  Returns the new row id.
        importance is auto-scored if not provided.
        """
        if importance is None:
            importance = self._scorer.score(content)
        if tags is None:
            tags = ",".join(self._scorer.extract_tags(content))
        ts = self._now()

        row_id = self._store_typed_memory(
            content=content,
            memory_type=memory_type,
            project=project,
            importance=importance,
            tags=tags,
            timestamp=ts,
        )

        # Also embed in ChromaDB memories collection
        if self._ensure_vector_client() and row_id:
            try:
                self.memory_collection.add(
                    documents=[content],
                    metadatas=[{
                        "memory_type": memory_type,
                        "project":     project,
                        "importance":  importance,
                        "tags":        tags,
                        "timestamp":   ts,
                    }],
                    ids=[f"mem_{row_id}_{memory_type}"],
                )
            except Exception as e:
                logger.error(f"Failed to embed memory: {e}")
        return row_id

    def store_semantic(self, content: str, project: str = "general", importance: int = None, tags: str = None) -> int:
        """Shortcut: store a semantic memory entry."""
        return self.store_memory(content=content, memory_type="semantic", project=project, importance=importance, tags=tags)

    def store_episodic(self, content: str, project: str = "general", importance: int = None) -> None:
        """Shortcut: store an episodic (experience) memory."""
        import os
        if os.environ.get("JARVIS_E2E_SIM") == "1":
            return
        if importance is None:
            importance = self._scorer.score(content)
        ts = self._now()
        with self._lock.write_lock():
            self.dbs["conversations"].execute(
                """INSERT INTO episodic_memories
                   (content, importance, project, event_date, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (content, importance, project, ts, ts),
            )
            self._commit()

    def store_procedural(self, skill_name: str, content: str, importance: int = 5) -> None:
        """Shortcut: store a procedural (how-to) memory."""
        ts = self._now()
        with self._lock.write_lock():
            self.dbs["conversations"].execute(
                """INSERT OR REPLACE INTO procedural_memories
                   (skill_name, content, importance, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (skill_name, content, importance, ts, ts),
            )
            self._commit()

    def _store_typed_memory(
        self,
        content: str,
        memory_type: str,
        project: str,
        importance: int,
        tags: str,
        timestamp: str,
    ) -> Optional[int]:
        """Write to the appropriate typed memory table and return the row id."""
        import os
        if memory_type == "episodic" and os.environ.get("JARVIS_E2E_SIM") == "1":
            return None
        with self._lock.write_lock():
            if memory_type == "episodic":
                cursor = self.dbs["conversations"].execute(
                    """INSERT INTO episodic_memories
                       (content, importance, project, event_date, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (content, importance, project, timestamp, timestamp),
                )
            elif memory_type == "procedural":
                import hashlib
                skill_name = f"auto_{hashlib.sha256(content.encode()).hexdigest()[:40]}"
                cursor = self.dbs["conversations"].execute(
                    """INSERT OR REPLACE INTO procedural_memories
                       (skill_name, content, importance, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (skill_name, content, importance, timestamp, timestamp),
                )
            else:
                # default: semantic
                cursor = self.dbs["conversations"].execute(
                    """INSERT INTO semantic_memories
                       (content, importance, project, tags, decay_score, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 1.0, ?, ?)""",
                    (content, importance, project, tags, timestamp, timestamp),
                )
                # If project-specific, also record in project_memories
                if project != "general":
                    self.dbs["conversations"].execute(
                        """INSERT INTO project_memories
                           (project_name, content, importance, tags, created_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (project, content, importance, tags, timestamp),
                    )
            self._commit()
            return cursor.lastrowid

    def set_working_memory(
        self, key: str, value: str, ttl_seconds: int = 3600
    ) -> None:
        """Store a volatile working-memory entry with a TTL."""
        ts         = self._now()
        expires_at = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat()
        with self._lock.write_lock():
            self.dbs["conversations"].execute(
                """INSERT OR REPLACE INTO working_memory (key, value, expires_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (key, value, expires_at, ts),
            )
            self._commit()

    def get_working_memory(self, key: str) -> Optional[str]:
        """Retrieve a working-memory entry if not expired."""
        now = self._now()
        with self._lock.read_lock():
            row = self.dbs["conversations"].execute(
                """SELECT value FROM working_memory
                   WHERE key = ? AND (expires_at IS NULL OR expires_at > ?)""",
                (key, now),
            ).fetchone()
        return row[0] if row else None

    def _purge_working_memory(self) -> None:
        """Delete expired working memory entries."""
        now = self._now()
        with self._lock.write_lock():
            self.dbs["conversations"].execute(
                "DELETE FROM working_memory WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            self._commit()

    def _sync_create_session(self, session_id: str, started_at: str, project: str) -> None:
        with self._lock.write_lock():
            # Find stale sessions (where ended_at is NULL)
            cursor = self.dbs["conversations"].execute(
                "SELECT session_id FROM sessions WHERE ended_at IS NULL"
            )
            stale_sessions = [row[0] for row in cursor.fetchall()]
            
            for old_sid in stale_sessions:
                logger.info(f"MemoryStore: Auto-closing stale session {old_sid}")
                self.dbs["conversations"].execute(
                    """UPDATE sessions
                       SET ended_at = ?, disconnect_reason = 'abrupt_exit'
                       WHERE session_id = ?""",
                    (started_at, old_sid),
                )
            
            self.dbs["conversations"].execute(
                """INSERT INTO sessions (session_id, started_at, project)
                   VALUES (?, ?, ?)""",
                (session_id, started_at, project),
            )
            self._commit()
            
        if stale_sessions:
            if not getattr(self, "_is_consolidating", False):
                self._is_consolidating = True
                try:
                    from modules.memory.consolidator import MemoryConsolidator
                    consolidator = MemoryConsolidator(self)
                    
                    def run_backfill():
                        try:
                            consolidator._backfill_missing_session_summaries()
                        finally:
                            self._is_consolidating = False
                            
                    import threading
                    threading.Thread(
                        target=run_backfill,
                        daemon=True
                    ).start()
                except Exception as e:
                    self._is_consolidating = False
                    logger.error(f"MemoryStore: failed to trigger startup backfill: {e}")

    def _sync_close_session(self, session_id: str, ended_at: str, disconnect_reason: str) -> None:
        with self._lock.write_lock():
            self.dbs["conversations"].execute(
                """UPDATE sessions
                   SET ended_at = ?, disconnect_reason = ?
                   WHERE session_id = ?""",
                (ended_at, disconnect_reason, session_id),
            )
            self._commit()

    def get_session_transcript(self, session_id: str) -> list:
        with self._lock.read_lock():
            cursor = self.dbs["conversations"].execute(
                "SELECT role, content FROM conversations WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            )
            results = cursor.fetchall()
        return [{"role": r[0], "content": r[1]} for r in results]

    def get_last_session_context(self) -> str:
        # Fetch last ended session with actual content
        with self._lock.read_lock():
            row = self.dbs["conversations"].execute(
                """SELECT session_id, ended_at, summary, topics FROM sessions
                   WHERE ended_at IS NOT NULL AND (summary IS NOT NULL OR turn_count > 0)
                   ORDER BY ended_at DESC, started_at DESC LIMIT 1"""
            ).fetchone()
            
        if not row:
            return ""
            
        session_id, ended_at_str, summary, topics = row
        
        # Build prompt section
        parts = [
            f"--- PREVIOUS SESSION (ended {ended_at_str}) ---"
        ]
        if summary:
            parts.append(f"Summary: {summary}")
            parts.append(f"Topics: {topics or 'None'}")
            
        # Parse ended_at to check recency (2 hours threshold)
        recency_threshold = int(os.getenv("JARVIS_SESSION_RECENCY_THRESHOLD_SECONDS", "7200"))
        is_recent = False
        try:
            ended_at = datetime.fromisoformat(ended_at_str)
            elapsed = (datetime.now() - ended_at).total_seconds()
            if elapsed < recency_threshold:
                is_recent = True
        except Exception:
            pass

        # Fetch last 10 turns
        transcript = self.get_session_transcript(session_id)
        if transcript and (is_recent or not summary):
            parts.append("\nLast few turns of the previous session:")
            for turn in transcript[-10:]:
                prefix = "User" if turn["role"] == "user" else "JARVIS"
                parts.append(f"  - [{prefix}] {turn['content']}")
                
        if not summary and not transcript:
            return ""
            
        return "\n".join(parts)

    def get_recent_sessions(self, limit: int = 20) -> list:
        with self._lock.read_lock():
            cursor = self.dbs["conversations"].execute(
                """SELECT session_id, started_at, ended_at, disconnect_reason, turn_count, summary, topics, project
                   FROM sessions
                   ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            )
            results = cursor.fetchall()
        return [
            {
                "session_id": r[0],
                "started_at": r[1],
                "ended_at": r[2],
                "disconnect_reason": r[3],
                "turn_count": r[4],
                "summary": r[5],
                "topics": r[6],
                "project": r[7],
            }
            for r in results
        ]

    def recall_past_sessions(self, query: str, when: str = None) -> str:
        # 1. Parse when
        start_date = None
        end_date = None
        
        if when:
            when_lower = when.lower().strip()
            now = datetime.now()
            today = now.date()
            if "today" in when_lower:
                start_date = today.isoformat()
            elif "yesterday" in when_lower:
                start_date = (today - timedelta(days=1)).isoformat()
                end_date = today.isoformat()
            elif "last week" in when_lower:
                start_date = (today - timedelta(days=7)).isoformat()
            elif "this week" in when_lower:
                start_date = (today - timedelta(days=now.weekday())).isoformat()
            else:
                # Try to parse as specific date (YYYY-MM-DD)
                import re
                match = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", when_lower)
                if match:
                    y, m, d = match.groups()
                    try:
                        parsed_dt = datetime(int(y), int(m), int(d))
                        start_date = parsed_dt.date().isoformat()
                        end_date = (parsed_dt + timedelta(days=1)).date().isoformat()
                    except ValueError:
                        pass

        # 2. Query summaries
        # If date range is specified, retrieve sessions in that range.
        with self._lock.read_lock():
            if start_date:
                sql = "SELECT session_id, started_at, summary, topics FROM sessions WHERE started_at >= ?"
                params = [start_date]
                if end_date:
                    sql += " AND started_at < ?"
                    params.append(end_date)
                sql += " ORDER BY started_at DESC LIMIT 5"
                rows = self.dbs["conversations"].execute(sql, params).fetchall()
                
                if rows:
                    parts = [f"Found {len(rows)} sessions in range '{when}':"]
                    for sid, started, summ, tops in rows:
                        parts.append(
                            f"\nSession ID: {sid}\n"
                            f"Started: {started}\n"
                            f"Topics: {tops or 'None'}\n"
                            f"Summary: {summ or 'No summary available.'}"
                        )
                    return "\n".join(parts)
            
            # If no date range specified or no rows found in range, perform FTS matching
            sql = """
                SELECT s.session_id, s.started_at, s.summary, s.topics, c.content, c.timestamp
                FROM conversations_fts f
                JOIN conversations c ON f.rowid = c.id
                JOIN sessions s ON c.session_id = s.session_id
                WHERE conversations_fts MATCH ?
                ORDER BY c.timestamp DESC LIMIT 5
            """
            # Escape query double quotes and wrap in double quotes for phrase search
            fts_query = f'"{query.replace("\"", "\"\"")}"'
            try:
                rows = self.dbs["conversations"].execute(sql, (fts_query,)).fetchall()
            except sqlite3.OperationalError:
                # Fallback in case of syntax error in match query
                rows = []
            
            if rows:
                parts = ["Found matching past conversations/sessions:"]
                seen_sessions = set()
                for sid, started, summ, tops, content, timestamp in rows:
                    if sid not in seen_sessions:
                        seen_sessions.add(sid)
                        parts.append(
                            f"\nSession ID: {sid}\n"
                            f"Started: {started}\n"
                            f"Topics: {tops or 'None'}\n"
                            f"Session Summary: {summ or 'No summary available.'}"
                        )
                    parts.append(f"  - [{timestamp}] Match: \"{content[:150]}...\"")
                return "\n".join(parts)
            
            # Fallback to searching sessions' summaries using LIKE
            sql = "SELECT session_id, started_at, summary, topics FROM sessions WHERE summary LIKE ? OR topics LIKE ? LIMIT 5"
            like_query = f"%{query}%"
            rows = self.dbs["conversations"].execute(sql, (like_query, like_query)).fetchall()
            if rows:
                parts = ["Found matching session summaries/topics:"]
                for sid, started, summ, tops in rows:
                    parts.append(
                        f"\nSession ID: {sid}\n"
                        f"Started: {started}\n"
                        f"Topics: {tops or 'None'}\n"
                        f"Summary: {summ or 'No summary available.'}"
                    )
                return "\n".join(parts)
                
            return f"No matching sessions or conversation turns found for '{query}'" + (f" within temporal constraint '{when}'" if when else "")
