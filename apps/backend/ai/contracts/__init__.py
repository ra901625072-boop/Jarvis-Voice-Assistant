"""
ai.contracts — Versioned inter-agent collaboration contracts and message envelopes.
"""
from .envelope import (
    MessageKind,
    Envelope,
    AgentTask,
    AgentResult,
    TaskPriority,
    VerificationReport,
    HandoffPacket,
    AgentTaskTypes,
)

__all__ = [
    "MessageKind",
    "Envelope",
    "AgentTask",
    "AgentResult",
    "TaskPriority",
    "VerificationReport",
    "HandoffPacket",
    "AgentTaskTypes",
]
