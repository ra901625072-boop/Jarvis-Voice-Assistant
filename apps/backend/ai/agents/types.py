"""
types.py — Re-exports from ai.contracts package for backward compatibility.
"""
from ai.contracts import (
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

