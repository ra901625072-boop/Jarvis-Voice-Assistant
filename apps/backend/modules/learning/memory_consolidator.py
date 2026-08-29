"""
memory_consolidator.py
----------------------
Consolidates raw execution episodes and lessons into high-level, generalizable strategies.
Implements the multi-stage memory validation & promotion pipeline:
  candidate -> validated -> trusted -> permanent (invariant)
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from collections import defaultdict

from modules.learning.evaluator_engine import EvaluatorEngine
from modules.learning.root_cause_analyzer import RootCauseAnalyzer

logger = logging.getLogger("JARVIS.MemoryConsolidator")


class MemoryConsolidator:
    """
    Consolidates episode experiences into validated strategies and manages the promotion lifecycle.
    """

    def __init__(self, memory_manager):
        self.mm = memory_manager
        self.evaluator = EvaluatorEngine()
        self.root_cause_analyzer = RootCauseAnalyzer()

    # ------------------------------------------------------------------ #
    # 1. Inductive Consolidation across Episodes                           #
    # ------------------------------------------------------------------ #

    def consolidate_episodes(self, min_cluster_size: int = 2) -> Dict[str, Any]:
        """
        Scans recent episodes, clusters patterns, and synthesizes candidate/validated strategies.
        """
        if not self.mm:
            return {"strategies_created": 0, "strategies_updated": 0}

        strategies_created = 0
        strategies_updated = 0

        try:
            with self.mm._lock:
                rows = self.mm.dbs["conversations"].execute(
                    """SELECT id, episode_id, agent_id, task_type, goal, trajectory_json,
                              outcome_json, success, created_at
                       FROM episodes ORDER BY id DESC LIMIT 100"""
                ).fetchall()

            if not rows:
                return {"strategies_created": 0, "strategies_updated": 0}

            # Cluster failures by root cause and successes by goal pattern
            failure_clusters = defaultdict(list)
            success_clusters = defaultdict(list)

            for r in rows:
                ep_dict = {
                    "id": r[0],
                    "episode_id": r[1],
                    "agent_id": r[2],
                    "task_type": r[3],
                    "goal": r[4] or "",
                    "trajectory": json.loads(r[5] or "[]"),
                    "outcome": json.loads(r[6] or "{}"),
                    "success": bool(r[7]),
                    "created_at": r[8],
                }

                if ep_dict["success"]:
                    key = f"{ep_dict['agent_id']}:{ep_dict['task_type']}"
                    success_clusters[key].append(ep_dict)
                else:
                    analysis = self.root_cause_analyzer.analyze(ep_dict)
                    key = f"{ep_dict['agent_id']}:{ep_dict['task_type']}:{analysis['root_cause_category']}"
                    failure_clusters[key].append((ep_dict, analysis))

            # Process Failure Clusters into Avoidance / Invariant Strategies
            for cluster_key, ep_list in failure_clusters.items():
                if len(ep_list) >= min_cluster_size:
                    sample_ep, sample_analysis = ep_list[0]
                    cat = sample_analysis["root_cause_category"]
                    strat_name = f"avoid_{sample_ep['agent_id']}_{sample_ep['task_type']}_{cat}"
                    
                    description = f"Preventative strategy for {sample_ep['agent_id']} during {sample_ep['task_type']} ({cat})."
                    trigger = f"task_type == '{sample_ep['task_type']}' and potential_{cat}"
                    guidance = sample_analysis.get("invariant_rule") or sample_analysis.get("preventative_guidance", "")
                    
                    source_ids = [ep[0]["episode_id"] for ep in ep_list]
                    utility = self._compute_utility(
                        importance=0.85 if cat == "invariant_violation" else 0.70,
                        confidence=min(0.95, 0.65 + 0.1 * len(ep_list)),
                        reusability=0.80,
                        generalization=0.75,
                    )
                    status = "trusted" if cat == "invariant_violation" else ("validated" if len(ep_list) >= 3 else "candidate")

                    res = self._upsert_strategy(
                        name=strat_name,
                        category=sample_ep["task_type"],
                        description=description,
                        trigger_condition=trigger,
                        action_guidance=guidance,
                        source_episodes=source_ids,
                        confidence=min(0.95, 0.65 + 0.1 * len(ep_list)),
                        utility_score=utility,
                        status=status,
                    )
                    if res == "created":
                        strategies_created += 1
                    elif res == "updated":
                        strategies_updated += 1

            # Process Success Clusters into Procedural Execution Strategies
            for cluster_key, ep_list in success_clusters.items():
                if len(ep_list) >= min_cluster_size:
                    sample_ep = ep_list[0]
                    strat_name = f"proc_{sample_ep['agent_id']}_{sample_ep['task_type']}_standard"
                    description = f"Proven execution procedure for {sample_ep['agent_id']} executing {sample_ep['task_type']}."
                    trigger = f"task_type == '{sample_ep['task_type']}'"
                    
                    # Synthesize step plan from trajectory
                    sample_traj = sample_ep.get("trajectory", [])
                    step_actions = [s.get("action") for s in sample_traj if s.get("action")]
                    guidance = f"Standard execution pipeline: {' -> '.join(step_actions[:5])}" if step_actions else f"Execute {sample_ep['task_type']} with standard verification."
                    
                    source_ids = [ep["episode_id"] for ep in ep_list]
                    utility = self._compute_utility(
                        importance=0.75,
                        confidence=min(0.95, 0.70 + 0.05 * len(ep_list)),
                        reusability=0.85,
                        generalization=0.80,
                    )
                    status = "validated" if len(ep_list) >= 3 else "candidate"

                    res = self._upsert_strategy(
                        name=strat_name,
                        category=sample_ep["task_type"],
                        description=description,
                        trigger_condition=trigger,
                        action_guidance=guidance,
                        source_episodes=source_ids,
                        confidence=min(0.95, 0.70 + 0.05 * len(ep_list)),
                        utility_score=utility,
                        status=status,
                    )
                    if res == "created":
                        strategies_created += 1
                    elif res == "updated":
                        strategies_updated += 1

        except Exception as e:
            logger.error(f"MemoryConsolidator: error during consolidation: {e}", exc_info=True)

        return {
            "strategies_created": strategies_created,
            "strategies_updated": strategies_updated,
        }

    # ------------------------------------------------------------------ #
    # 2. Strategy Upsert & Lifecycle Management                           #
    # ------------------------------------------------------------------ #

    def _compute_utility(self, importance: float, confidence: float, reusability: float, generalization: float) -> float:
        """Utility = Importance * Confidence * Reusability * Generalization"""
        return round(importance * confidence * reusability * generalization, 4)

    def _upsert_strategy(
        self,
        name: str,
        category: str,
        description: str,
        trigger_condition: str,
        action_guidance: str,
        source_episodes: List[str],
        confidence: float,
        utility_score: float,
        status: str = "candidate",
    ) -> str:
        ts = datetime.now().isoformat()
        with self.mm._lock:
            existing = self.mm.dbs["conversations"].execute(
                "SELECT id, status, confidence FROM strategies WHERE name = ?",
                (name,),
            ).fetchone()

            if existing:
                strat_id, old_status, old_conf = existing
                # If old status was permanent or trusted, don't downgrade
                new_status = old_status if old_status in ("permanent", "trusted") else status
                new_conf = max(old_conf, confidence)

                self.mm.dbs["conversations"].execute(
                    """UPDATE strategies SET
                       description = ?,
                       trigger_condition = ?,
                       action_guidance = ?,
                       source_episodes_json = ?,
                       confidence = ?,
                       utility_score = ?,
                       status = ?,
                       updated_at = ?
                       WHERE id = ?""",
                    (
                        description,
                        trigger_condition,
                        action_guidance,
                        json.dumps(source_episodes),
                        new_conf,
                        utility_score,
                        new_status,
                        ts,
                        strat_id,
                    ),
                )
                self.mm.dbs["conversations"].commit()

                if old_status != new_status:
                    self._record_promotion("strategy", str(strat_id), old_status, new_status, "Consolidation frequency threshold reached")

                return "updated"
            else:
                cursor = self.mm.dbs["conversations"].execute(
                    """INSERT INTO strategies
                       (name, category, description, trigger_condition, action_guidance,
                        source_episodes_json, confidence, utility_score, status,
                        success_count, fail_count, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)""",
                    (
                        name,
                        category,
                        description,
                        trigger_condition,
                        action_guidance,
                        json.dumps(source_episodes),
                        confidence,
                        utility_score,
                        status,
                        ts,
                        ts,
                    ),
                )
                strat_id = cursor.lastrowid
                self.mm.dbs["conversations"].commit()
                self._record_promotion("strategy", str(strat_id), "none", status, "Initial candidate strategy synthesis")
                return "created"

    def promote_strategy(self, strategy_id: int, target_status: str, reason: str) -> bool:
        """Promotes a strategy along the lifecycle: candidate -> validated -> trusted -> permanent."""
        if not self.mm:
            return False
        valid_transitions = {
            "candidate": ["validated", "rejected"],
            "validated": ["trusted", "candidate"],
            "trusted": ["permanent", "validated"],
            "permanent": [],
        }

        ts = datetime.now().isoformat()
        with self.mm._lock:
            row = self.mm.dbs["conversations"].execute(
                "SELECT id, status FROM strategies WHERE id = ?",
                (strategy_id,),
            ).fetchone()
            if not row:
                return False

            current_status = row[1]
            if target_status not in valid_transitions.get(current_status, []):
                logger.warning(f"Invalid strategy transition: {current_status} -> {target_status}")
                return False

            self.mm.dbs["conversations"].execute(
                "UPDATE strategies SET status = ?, updated_at = ? WHERE id = ?",
                (target_status, ts, strategy_id),
            )
            self.mm.dbs["conversations"].commit()
            self._record_promotion("strategy", str(strategy_id), current_status, target_status, reason)
            return True

    def _record_promotion(self, entity_type: str, entity_id: str, from_status: str, to_status: str, reason: str) -> None:
        ts = datetime.now().isoformat()
        try:
            self.mm.dbs["conversations"].execute(
                """INSERT INTO memory_promotions (entity_type, entity_id, from_status, to_status, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (entity_type, entity_id, from_status, to_status, reason, ts),
            )
            self.mm.dbs["conversations"].commit()
        except Exception as e:
            logger.error(f"MemoryConsolidator: failed to record promotion: {e}")

    def get_active_strategies(self, category: Optional[str] = None, min_status: str = "validated") -> List[Dict[str, Any]]:
        """Retrieves operational strategies with status >= min_status."""
        if not self.mm:
            return []

        status_ranks = {"candidate": 0, "validated": 1, "trusted": 2, "permanent": 3}
        target_rank = status_ranks.get(min_status, 1)

        allowed_statuses = [s for s, rank in status_ranks.items() if rank >= target_rank]
        placeholders = ",".join("?" for _ in allowed_statuses)

        query = f"SELECT id, name, category, description, trigger_condition, action_guidance, confidence, utility_score, status FROM strategies WHERE status IN ({placeholders})"
        params: List[Any] = list(allowed_statuses)

        if category:
            query += " AND (category = ? OR category = 'general')"
            params.append(category)

        query += " ORDER BY utility_score DESC"

        with self.mm._lock:
            rows = self.mm.dbs["conversations"].execute(query, tuple(params)).fetchall()

        results = []
        for r in rows:
            results.append({
                "id": r[0],
                "name": r[1],
                "category": r[2],
                "description": r[3],
                "trigger_condition": r[4],
                "action_guidance": r[5],
                "confidence": r[6],
                "utility_score": r[7],
                "status": r[8],
            })
        return results
