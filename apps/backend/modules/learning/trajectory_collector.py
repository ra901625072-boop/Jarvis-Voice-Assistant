"""
trajectory_collector.py
-----------------------
Captures complete end-to-end execution trajectories (Goal -> Plan -> Action -> Tool -> Observation -> Thought -> Result -> Evaluation)
and persists them into the `episodes` SQLite table.

This enables JARVIS to learn from the exact causal chains of execution rather than just flat outcomes.
"""

import json
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("JARVIS.TrajectoryCollector")


class EpisodeStep:
    def __init__(
        self,
        step_idx: int,
        action: str,
        tool_name: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None,
        observation: Optional[Any] = None,
        thought: Optional[str] = None,
        error: Optional[str] = None,
        duration_ms: float = 0.0,
        timestamp: Optional[str] = None,
    ):
        self.step_idx = step_idx
        self.action = action
        self.tool_name = tool_name
        self.args = args or {}
        self.observation = observation
        self.thought = thought
        self.error = error
        self.duration_ms = duration_ms
        self.timestamp = timestamp or datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_idx": self.step_idx,
            "action": self.action,
            "tool_name": self.tool_name,
            "args": self.args,
            "observation": str(self.observation) if self.observation is not None else None,
            "thought": self.thought,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
        }


class TrajectoryCollector:
    """
    Collects full execution traces for an agent task and persists them to the episodes table.
    """

    def __init__(
        self,
        agent_id: str,
        task_type: str,
        goal: str = "",
        context: Optional[Dict[str, Any]] = None,
        plan: Optional[List[Dict[str, Any]]] = None,
        episode_id: Optional[str] = None,
    ):
        self.episode_id = episode_id or f"ep_{uuid.uuid4().hex[:12]}"
        self.agent_id = agent_id
        self.task_type = task_type
        self.goal = goal
        self.context = context or {}
        self.plan = plan or []
        self.steps: List[EpisodeStep] = []
        self.outcome: Dict[str, Any] = {}
        self.evaluation: Optional[Dict[str, Any]] = None
        self.duration_ms: float = 0.0
        self.tokens_used: int = 0
        self.cost_usd: float = 0.0
        self.success: bool = False
        self.created_at = datetime.now().isoformat()
        self._finalized = False

    def add_step(
        self,
        action: str,
        tool_name: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None,
        observation: Optional[Any] = None,
        thought: Optional[str] = None,
        error: Optional[str] = None,
        duration_ms: float = 0.0,
    ) -> EpisodeStep:
        """Appends a new action/observation step to the trajectory."""
        step_idx = len(self.steps) + 1
        step = EpisodeStep(
            step_idx=step_idx,
            action=action,
            tool_name=tool_name,
            args=args,
            observation=observation,
            thought=thought,
            error=error,
            duration_ms=duration_ms,
        )
        self.steps.append(step)
        return step

    def set_plan(self, plan: List[Dict[str, Any]]) -> None:
        """Sets or updates the high-level plan for this episode."""
        self.plan = plan

    def finalize(
        self,
        success: bool,
        result: Any = None,
        error: Optional[str] = None,
        duration_ms: float = 0.0,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        evaluation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Finalizes the episode state and returns the serialized payload."""
        self.success = bool(success)
        self.duration_ms = duration_ms
        self.tokens_used = tokens_used
        self.cost_usd = cost_usd
        self.evaluation = evaluation
        self.outcome = {
            "success": self.success,
            "result": str(result) if result is not None else None,
            "error": str(error) if error is not None else None,
            "duration_ms": self.duration_ms,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
        }
        self._finalized = True
        return self.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "agent_id": self.agent_id,
            "task_type": self.task_type,
            "goal": self.goal,
            "context": self.context,
            "plan": self.plan,
            "trajectory": [s.to_dict() for s in self.steps],
            "outcome": self.outcome,
            "duration_ms": self.duration_ms,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "success": self.success,
            "evaluation": self.evaluation,
            "created_at": self.created_at,
        }

    def save_to_db(self, memory_manager) -> Optional[str]:
        """Persists the finalized episode to SQLite."""
        if not memory_manager:
            return None
        if not self._finalized:
            self.finalize(success=self.success, duration_ms=self.duration_ms)

        try:
            with memory_manager._lock:
                memory_manager.dbs["conversations"].execute(
                    """INSERT INTO episodes
                       (episode_id, agent_id, task_type, goal, context_json, plan_json,
                        trajectory_json, outcome_json, duration_ms, tokens_used, cost_usd,
                        success, evaluation_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(episode_id) DO UPDATE SET
                       outcome_json=excluded.outcome_json,
                       trajectory_json=excluded.trajectory_json,
                       evaluation_json=excluded.evaluation_json,
                       success=excluded.success,
                       duration_ms=excluded.duration_ms""",
                    (
                        self.episode_id,
                        self.agent_id,
                        self.task_type,
                        self.goal,
                        json.dumps(self.context),
                        json.dumps(self.plan),
                        json.dumps([s.to_dict() for s in self.steps]),
                        json.dumps(self.outcome),
                        self.duration_ms,
                        self.tokens_used,
                        self.cost_usd,
                        1 if self.success else 0,
                        json.dumps(self.evaluation) if self.evaluation else None,
                        self.created_at,
                    ),
                )
                memory_manager.dbs["conversations"].commit()
            logger.debug(f"TrajectoryCollector: persisted episode {self.episode_id} for {self.agent_id}")
            return self.episode_id
        except Exception as e:
            logger.error(f"TrajectoryCollector: failed to persist episode {self.episode_id}: {e}", exc_info=True)
            return None

    @classmethod
    def get_episode(cls, memory_manager, episode_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single episode by ID."""
        if not memory_manager:
            return None
        try:
            with memory_manager._lock:
                row = memory_manager.dbs["conversations"].execute(
                    """SELECT episode_id, agent_id, task_type, goal, context_json, plan_json,
                              trajectory_json, outcome_json, duration_ms, tokens_used, cost_usd,
                              success, evaluation_json, created_at
                       FROM episodes WHERE episode_id = ?""",
                    (episode_id,),
                ).fetchone()
                if not row:
                    return None
                return {
                    "episode_id": row[0],
                    "agent_id": row[1],
                    "task_type": row[2],
                    "goal": row[3],
                    "context": json.loads(row[4] or "{}"),
                    "plan": json.loads(row[5] or "[]"),
                    "trajectory": json.loads(row[6] or "[]"),
                    "outcome": json.loads(row[7] or "{}"),
                    "duration_ms": row[8],
                    "tokens_used": row[9],
                    "cost_usd": row[10],
                    "success": bool(row[11]),
                    "evaluation": json.loads(row[12]) if row[12] else None,
                    "created_at": row[13],
                }
        except Exception as e:
            logger.error(f"TrajectoryCollector: error fetching episode {episode_id}: {e}")
            return None

    @classmethod
    def get_recent_episodes(
        cls,
        memory_manager,
        agent_id: Optional[str] = None,
        task_type: Optional[str] = None,
        limit: int = 20,
        success_only: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves recent episodes matching filters."""
        if not memory_manager:
            return []
        try:
            query = "SELECT episode_id, agent_id, task_type, goal, context_json, plan_json, trajectory_json, outcome_json, duration_ms, tokens_used, cost_usd, success, evaluation_json, created_at FROM episodes WHERE 1=1"
            params: List[Any] = []
            if agent_id:
                query += " AND agent_id = ?"
                params.append(agent_id)
            if task_type:
                query += " AND task_type = ?"
                params.append(task_type)
            if success_only is not None:
                query += " AND success = ?"
                params.append(1 if success_only else 0)

            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)

            with memory_manager._lock:
                rows = memory_manager.dbs["conversations"].execute(query, tuple(params)).fetchall()

            results = []
            for row in rows:
                results.append({
                    "episode_id": row[0],
                    "agent_id": row[1],
                    "task_type": row[2],
                    "goal": row[3],
                    "context": json.loads(row[4] or "{}"),
                    "plan": json.loads(row[5] or "[]"),
                    "trajectory": json.loads(row[6] or "[]"),
                    "outcome": json.loads(row[7] or "{}"),
                    "duration_ms": row[8],
                    "tokens_used": row[9],
                    "cost_usd": row[10],
                    "success": bool(row[11]),
                    "evaluation": json.loads(row[12]) if row[12] else None,
                    "created_at": row[13],
                })
            return results
        except Exception as e:
            logger.error(f"TrajectoryCollector: error fetching recent episodes: {e}")
            return []
