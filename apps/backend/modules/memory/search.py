import re
import math
import time
import logging
from functools import wraps
import threading as _threading
from typing import Optional, List, Dict, Any

logger = logging.getLogger("JARVIS.MemorySearch")

def ttl_cache(maxsize=100, ttl=300):
    """Thread-safe TTL cache decorator with LRU eviction."""
    cache = {}
    _lock = _threading.Lock()
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            key = str(args) + str(kwargs)
            now = time.time()
            with _lock:
                if key in cache:
                    result, timestamp = cache[key]
                    if now - timestamp < ttl:
                        return result
                    else:
                        del cache[key]
            result = func(self, *args, **kwargs)
            with _lock:
                cache[key] = (result, now)
                # LRU eviction: remove oldest entry when over max size
                if len(cache) > maxsize:
                    oldest_key = next(iter(cache))
                    del cache[oldest_key]
            return result
        return wrapper
    return decorator


class MemorySearchMixin:
    def search_semantic(self, query: str, project: str = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Shortcut: search semantic memories."""
        return self.search_memories(query=query, memory_type="semantic", project=project, limit=limit)

    @ttl_cache(maxsize=100, ttl=300)
    def search_memories(
        self,
        query: str,
        memory_type: str = None,
        project: str = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search across all typed memories.
        Filters by memory_type and/or project if provided.
        """
        start_t = time.perf_counter()
        
        # Try SQLite FTS first for speed
        fts_results = self._fts_memory_fallback(query, memory_type, project, limit=10)
        
        # If we got strong results from SQLite, return them and skip ChromaDB
        if fts_results and len(fts_results) >= limit // 2:
            logger.info(f"Memory retrieval (SQLite): {time.perf_counter() - start_t:.3f}s")
            return fts_results[:limit]
            
        # Try ChromaDB memories collection as fallback
        if self._ensure_vector_client():
            try:
                filter_items = []
                if memory_type:
                    filter_items.append({"memory_type": {"$eq": memory_type}})
                if project:
                    filter_items.append({"project": {"$eq": project}})

                where_filter = {}
                if len(filter_items) == 1:
                    where_filter = filter_items[0]
                elif len(filter_items) > 1:
                    where_filter = {"$and": filter_items}

                kwargs: Dict[str, Any] = {
                    "query_texts": [query],
                    "n_results":   min(limit * 3, 50),
                }
                if where_filter:
                    kwargs["where"] = where_filter

                res = self.memory_collection.query(**kwargs)
                if res and res["documents"] and res["documents"][0]:
                    candidates = []
                    for doc, meta, dist in zip(
                        res["documents"][0],
                        res["metadatas"][0],
                        res["distances"][0],
                    ):
                        vector_sim   = max(0.0, 1.0 - dist)
                        imp          = meta.get("importance", 5) / 10.0
                        ts_str       = meta.get("timestamp", self._now())
                        age_days     = self._age_days(ts_str)
                        recency      = math.exp(-0.05 * age_days)
                        final_score  = 0.5 * vector_sim + 0.3 * imp + 0.2 * recency
                        candidates.append({
                            "content":     doc,
                            "memory_type": meta.get("memory_type", "semantic"),
                            "project":     meta.get("project", "general"),
                            "importance":  meta.get("importance", 5),
                            "tags":        meta.get("tags", ""),
                            "score":       final_score,
                        })
                    candidates.sort(key=lambda x: x["score"], reverse=True)
                    logger.info(f"Memory retrieval (Hybrid DB): {time.perf_counter() - start_t:.3f}s")
                    return candidates[:limit]
            except Exception as e:
                logger.error(f"Memory search (ChromaDB) failed: {e}")

        # SQLite fallback if vector search fails completely
        logger.info(f"Memory retrieval (Fallback): {time.perf_counter() - start_t:.3f}s")
        return fts_results[:limit]

    @ttl_cache(maxsize=100, ttl=300)
    def get_project_context(self, project_name: str) -> str:
        """Return all memories tagged to a specific project as a formatted string."""
        with self._lock.read_lock():
            rows = self.dbs["conversations"].execute(
                """SELECT content, importance FROM semantic_memories
                   WHERE project = ? ORDER BY importance DESC, updated_at DESC LIMIT 20""",
                (project_name,),
            ).fetchall()
            pm_rows = self.dbs["conversations"].execute(
                """SELECT content, importance FROM project_memories
                   WHERE project_name = ? ORDER BY importance DESC LIMIT 10""",
                (project_name,),
            ).fetchall()

        all_rows = sorted(rows + pm_rows, key=lambda r: r[1], reverse=True)
        if not all_rows:
            return f"No memories found for project: {project_name}"

        lines = [f"--- PROJECT CONTEXT: {project_name.upper()} ---"]
        for content, imp in all_rows[:15]:
            lines.append(f"[imp:{imp}] {content[:250]}")
        return "\n".join(lines)

    def _hybrid_search(
        self,
        query: str,
        collection=None,
        memory_type: str = None,
        project: str = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Phase 5 hybrid retrieval:
          Score = 0.40 x vector_similarity
                + 0.25 x (importance / 10)
                + 0.20 x recency
                + 0.15 x goal_relevance     <- Phase 5 addition
        Falls back to FTS if ChromaDB is unavailable.
        """
        candidates = []

        # Pre-compute goal relevance scorer (lazy — avoid circular init)
        try:
            _goal_scorer = self.lifecycle.goal_memory.goal_relevance_score
        except Exception:
            _goal_scorer = None

        # --- Vector path ---
        if self._ensure_vector_client() and collection is not None:
            try:
                kwargs: Dict[str, Any] = {
                    "query_texts": [query],
                    "n_results":   min(limit * 4, 50),
                }
                res = collection.query(**kwargs)
                if res and res["documents"] and res["documents"][0]:
                    for doc, meta, dist in zip(
                        res["documents"][0],
                        res["metadatas"][0],
                        res["distances"][0],
                    ):
                        vector_sim   = max(0.0, 1.0 - dist)
                        imp          = meta.get("importance", 3) / 10.0
                        ts_str       = meta.get("timestamp", self._now())
                        age_days     = self._age_days(ts_str)
                        recency      = math.exp(-0.05 * age_days)
                        goal_rel     = _goal_scorer(doc) if _goal_scorer else 0.0
                        final_score  = (0.40 * vector_sim
                                      + 0.25 * imp
                                      + 0.20 * recency
                                      + 0.15 * goal_rel)
                        candidates.append({
                            "timestamp":   ts_str,
                            "role":        meta.get("role", "user"),
                            "content":     doc,
                            "memory_type": meta.get("memory_type", "general"),
                            "project":     meta.get("project", "general"),
                            "importance":  meta.get("importance", 3),
                            "score":       final_score,
                        })
            except Exception as e:
                logger.error(f"Hybrid vector search failed: {e}")

        # --- FTS fallback / supplement ---
        if len(candidates) < limit:
            fts_rows = self._fts_search_raw(query, limit * 2)
            existing_contents = {c["content"] for c in candidates}
            for row in fts_rows:
                if row["content"] not in existing_contents:
                    imp        = row.get("importance", 3) / 10.0
                    age_days   = self._age_days(row.get("timestamp", self._now()))
                    recency    = math.exp(-0.05 * age_days)
                    goal_rel   = _goal_scorer(row["content"]) if _goal_scorer else 0.0
                    row["score"] = (0.25 * imp + 0.20 * recency + 0.15 * goal_rel)
                    candidates.append(row)

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:limit]

    def _fts_search_raw(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Raw FTS search against conversations table."""
        try:
            safe_q = query.replace('"', "").replace("'", "")
            with self._lock.read_lock():
                rows = self.dbs["conversations"].execute(
                    """SELECT c.timestamp, c.role, c.content,
                              COALESCE(c.importance, 3),
                              COALESCE(c.memory_type, 'general'),
                              COALESCE(c.project, 'general')
                       FROM conversations c
                       JOIN conversations_fts fts ON c.id = fts.rowid
                       WHERE conversations_fts MATCH ?
                       ORDER BY fts.rank
                       LIMIT ?""",
                    (f'"{safe_q}*"', limit),
                ).fetchall()
            return [
                {
                    "timestamp":   r[0],
                    "role":        r[1],
                    "content":     r[2],
                    "importance":  r[3],
                    "memory_type": r[4],
                    "project":     r[5],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"FTS search failed: {e}")
            return []

    def _fts_memory_fallback(
        self,
        query: str,
        memory_type: Optional[str],
        project: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Fallback: search semantic_memories by FTS5 or keyword tokens."""
        try:
            words = [w.strip() for w in re.findall(r"\w+", query) if len(w) > 2]
            if not words:
                words = [query.strip()] if query.strip() else []
            if not words:
                return []

            # 1. Try semantic_memories_fts table first
            try:
                fts_query = " OR ".join([f'"{w}"' for w in words])
                fts_sql = """
                    SELECT sm.content, sm.importance, sm.project, sm.tags
                    FROM semantic_memories sm
                    JOIN semantic_memories_fts fts ON sm.id = fts.rowid
                    WHERE semantic_memories_fts MATCH ?
                """
                params: list = [fts_query]
                if project:
                    fts_sql += " AND sm.project = ?"
                    params.append(project)
                fts_sql += " ORDER BY sm.importance DESC LIMIT ?"
                params.append(limit)
                with self._lock.read_lock():
                    rows = self.dbs["conversations"].execute(fts_sql, params).fetchall()
                if rows:
                    return [
                        {
                            "content":     r[0],
                            "importance":  r[1],
                            "project":     r[2],
                            "tags":        r[3],
                            "memory_type": "semantic",
                            "score":       r[1] / 10.0,
                        }
                        for r in rows
                    ]
            except Exception:
                pass

            # 2. Fallback to multi-keyword LIKE
            likes = " OR ".join(["content LIKE ?" for _ in words])
            sql = f"SELECT content, importance, project, tags FROM semantic_memories WHERE ({likes})"
            params = [f"%{w}%" for w in words]
            if project:
                sql += " AND project = ?"
                params.append(project)
            sql += " ORDER BY importance DESC LIMIT ?"
            params.append(limit)
            with self._lock.read_lock():
                rows = self.dbs["conversations"].execute(sql, params).fetchall()
            return [
                {
                    "content":     r[0],
                    "importance":  r[1],
                    "project":     r[2],
                    "tags":        r[3],
                    "memory_type": "semantic",
                    "score":       r[1] / 10.0,
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"FTS memory fallback failed: {e}")
            return []
