"""
trace.py — Observability tracing and telemetry aggregation store.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import time
import uuid
import logging

logger = logging.getLogger("JARVIS.Observability")

@dataclass
class SpanEvent:
    name: str           # e.g. "tool_called", "agent_dispatched"
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TraceSpan:
    span_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    trace_id: str = ""
    agent_id: str = ""
    task_type: str = ""
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    success: Optional[bool] = None
    tokens_used: int = 0
    cost_usd: float = 0.0
    confidence: float = 0.0
    retries: int = 0
    error: Optional[str] = None
    events: List[SpanEvent] = field(default_factory=list)

    def finish(self, success: bool, error: str = None):
        self.end_time = time.time()
        self.success = success
        self.error = error

    @property
    def duration_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time) * 1000.0
        return 0.0

class TelemetryStore:
    def __init__(self):
        self._spans: List[TraceSpan] = []

    def record_span(self, span: TraceSpan):
        self._spans.append(span)
        logger.debug(f"Telemetry recorded: {span.agent_id} ({span.task_type}) success={span.success} duration={span.duration_ms:.1f}ms")

    def get_agent_metrics(self, agent_id: str, task_type: Optional[str] = None) -> Dict[str, Any]:
        relevant = [
            s for s in self._spans
            if s.agent_id == agent_id and (task_type is None or s.task_type == task_type) and s.success is not None
        ]
        if not relevant:
            return {"total": 0, "success_rate": 0.8, "avg_duration_ms": 0.0, "total_cost_usd": 0.0}

        successes = sum(1 for s in relevant if s.success)
        total = len(relevant)
        avg_dur = sum(s.duration_ms for s in relevant) / total
        total_cost = sum(s.cost_usd for s in relevant)

        return {
            "total": total,
            "success_rate": round(successes / total, 4),
            "avg_duration_ms": round(avg_dur, 2),
            "total_cost_usd": round(total_cost, 6),
        }
