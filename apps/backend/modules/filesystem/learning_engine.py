import time
import logging
import json
import os
import threading
from modules.filesystem.fs_db import FSDatabase

logger = logging.getLogger("JARVIS.LearningEngine")

class LearningEngine:
    def __init__(self, db: FSDatabase):
        self.db = db
        self.state_file = os.path.join(os.path.dirname(db.db_path), "learning_state.json")
        self.state = self._load_state()
        self._stop_event = threading.Event()
        import sys
        if "pytest" not in sys.modules and "PYTEST_CURRENT_TEST" not in os.environ:
            self._recalibration_thread = threading.Thread(target=self._periodic_recalibration, daemon=True)
            self._recalibration_thread.start()
        else:
            self._recalibration_thread = None

    def close(self):
        self._stop_event.set()

    def _load_state(self):
        default_state = {
            "weights": {
                "fuzzy_score": 0.35,
                "recency_score": 0.15,
                "history_boost": 0.15,
                "alias_confidence": 0.20,
                "source_confidence": 0.15
            },
            "skip_lists": {},
            "folder_priority": {}
        }
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load learning state: {e}")
        return default_state

    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save learning state: {e}")

    def record(self, query: str, resolved_path: str, stage: str, confidence: float, outcome: str = "success"):
        """
        Records a search resolution attempt.
        Outcome can be 'success', 'not_found', 'ambiguous', 'rejected'.
        """
        try:
            query_norm = query.strip().lower()
            if not query_norm:
                return
                
            now = time.time()
            
            # Record audit row unconditionally
            with self.db._db_lock:
                self.db.db_conn.execute("""
                    INSERT INTO search_audit (query, resolved_path, stage, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (query_norm, resolved_path if resolved_path else outcome, stage, str(now)))
                
                # Only upsert alias on success
                if outcome == "success" and resolved_path:
                    self.db.db_conn.execute("""
                        INSERT INTO file_aliases (query_normalized, path, hit_count, confidence, last_used)
                        VALUES (?, ?, 1, ?, ?)
                        ON CONFLICT(query_normalized, path) DO UPDATE SET
                            hit_count = hit_count + 1,
                            confidence = excluded.confidence,
                            last_used = excluded.last_used
                        """, (query_norm, resolved_path, confidence, now))
                self.db.db_conn.commit()
                
            if outcome == "success" and resolved_path:
                self.db.log_access(resolved_path, str(now))
            logger.info(f"Recorded task outcome '{outcome}': '{query_norm}' -> {resolved_path} ({stage})")
        except Exception as e:
            logger.error(f"Failed to record task outcome: {e}")
            
    def _periodic_recalibration(self):
        """
        Background thread that periodically wakes up to decay aliases and adjust weights.
        """
        while not self._stop_event.is_set():
            if self._stop_event.wait(3600):
                break
            try:
                now = time.time()
                ninety_days_ago = now - (90 * 86400)
                with self.db._db_lock:
                    self.db.db_conn.execute("""
                        UPDATE file_aliases 
                        SET confidence = confidence * 0.8 
                        WHERE last_used < ? AND confidence > 10.0
                    """, (ninety_days_ago,))
                    self.db.db_conn.commit()
                    
                # Here we could compute deltas from search_audit to adjust self.state["weights"]
                # bounded within +-15% and save state. For now we just flush to ensure sanity.
                self._save_state()
            except Exception as e:
                logger.error(f"Failed periodic recalibration: {e}")

