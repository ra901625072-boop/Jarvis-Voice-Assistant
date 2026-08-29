"""
risk_gate.py — Policy, Risk and Budget Gatekeeper for Jarvis Planning Agent.
Enforces pre-flight risk checks, human-in-the-loop (HITL) approval gates,
and execution resource budget circuit breakers.
"""
from __future__ import annotations
import logging
import time
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple, Awaitable

from modules.planning.task_graph import TaskNode, RiskLevel
from modules.approval.engine import ApprovalEngine, RiskLevel as ApprovalRiskLevel, ApprovalRequest

logger = logging.getLogger("JARVIS.RiskGate")


@dataclass
class RiskAssessment:
    task_id: str
    risk_level: RiskLevel
    requires_approval: bool
    reason: str
    action_summary: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanningBudget:
    """
    Tracks and constrains resource consumption for a goal execution session.
    """
    max_execution_time_seconds: float = 1800.0   # 30 mins
    max_tool_invocations: int = 100
    max_retries_per_node: int = 3
    max_global_recoveries: int = 5
    max_cost_usd: float = 5.0
    
    # Live counters
    start_time: float = field(default_factory=time.time)
    tool_invocations_count: int = 0
    total_tokens_used: int = 0
    total_cost_usd: float = 0.0
    global_recovery_count: int = 0

    def check_budget(self) -> Tuple[bool, Optional[str]]:
        """
        Validates whether current execution is within budget limits.
        Returns (is_ok, failure_reason).
        """
        elapsed = time.time() - self.start_time
        if elapsed > self.max_execution_time_seconds:
            return False, f"Execution time limit exceeded ({elapsed:.1f}s > {self.max_execution_time_seconds}s)"
        
        if self.tool_invocations_count >= self.max_tool_invocations:
            return False, f"Maximum tool invocations reached ({self.tool_invocations_count} >= {self.max_tool_invocations})"
            
        if self.global_recovery_count >= self.max_global_recoveries:
            return False, f"Maximum global recovery limit reached ({self.global_recovery_count} >= {self.max_global_recoveries})"
            
        if self.total_cost_usd >= self.max_cost_usd:
            return False, f"Total API cost budget exceeded (${self.total_cost_usd:.2f} >= ${self.max_cost_usd:.2f})"
            
        return True, None

    def record_tool_call(self, tokens: int = 0, cost_usd: float = 0.0):
        self.tool_invocations_count += 1
        self.total_tokens_used += tokens
        self.total_cost_usd += cost_usd

    def record_recovery(self):
        self.global_recovery_count += 1


class RiskGate:
    """
    Gatekeeper that assesses task risk and enforces HITL authorization policies.
    """
    # Shell commands or operations that are immediately CRITICAL
    CRITICAL_PATTERNS = [
        "rm -rf", "del /f", "format ", "mkfs", "drop database", "truncate table",
        "shutdown", "restart-computer", "stop-computer", "fdisk", "diskpart",
        "chmod -r 777", "reg delete", "remove-item -recurse"
    ]

    # Commands requiring confirmation
    HIGH_RISK_PATTERNS = [
        "pip install", "npm install", "git push", "git commit", "kill", "taskkill",
        "overwrite", "move", "rename", "pkill"
    ]

    def __init__(
        self,
        approval_engine: Optional[ApprovalEngine] = None,
        security_manager = None,
        budget: Optional[PlanningBudget] = None
    ):
        self.approval_engine = approval_engine or ApprovalEngine()
        self.security_manager = security_manager
        self.budget = budget or PlanningBudget()

    def evaluate_node(self, node: TaskNode) -> RiskAssessment:
        """
        Assesses the risk level of a TaskNode before execution.
        """
        tool_name = (node.tool_name or "").lower()
        args = node.args or {}
        args_str = str(args).lower()
        desc = (node.title or node.description).lower()

        # 1. Critical pattern checks
        for pattern in self.CRITICAL_PATTERNS:
            if pattern in args_str or pattern in desc:
                return RiskAssessment(
                    task_id=node.task_id,
                    risk_level=RiskLevel.CRITICAL,
                    requires_approval=True,
                    reason=f"Destructive pattern detected: '{pattern}'",
                    action_summary=f"Critical operation: {node.title}"
                )

        # 2. Filesystem deletion / wipe tools
        if any(w in tool_name for w in ["delete_file", "delete_directory", "format_drive", "delete_all"]):
            return RiskAssessment(
                task_id=node.task_id,
                risk_level=RiskLevel.CRITICAL,
                requires_approval=True,
                reason="Destructive filesystem modification tool invocation.",
                action_summary=f"Delete action: {node.title}"
            )

        # 3. High risk shell execution
        if any(w in tool_name for w in ["execute_command", "run_shell_command", "run_terminal_command", "run_python_code"]):
            for h_pattern in self.HIGH_RISK_PATTERNS:
                if h_pattern in args_str or h_pattern in desc:
                    return RiskAssessment(
                        task_id=node.task_id,
                        risk_level=RiskLevel.HIGH,
                        requires_approval=False,  # Can execute with warning/audit unless auto-confirm is off
                        reason=f"High-risk command parameter: '{h_pattern}'",
                        action_summary=f"Terminal command: {node.title}"
                    )
            return RiskAssessment(
                task_id=node.task_id,
                risk_level=RiskLevel.HIGH,
                requires_approval=False,
                reason="Generic terminal or script execution.",
                action_summary=f"Execute: {node.title}"
            )

        # 4. Medium risk (writing files, browser actions)
        if any(w in tool_name for w in ["create_file", "write_file", "write_code", "open_url", "click_dom"]):
            return RiskAssessment(
                task_id=node.task_id,
                risk_level=RiskLevel.MEDIUM,
                requires_approval=False,
                reason="File mutation or interactive browser automation.",
                action_summary=f"Modify/Browse: {node.title}"
            )

        # 5. Low risk default (reading, searching, linting, inspecting)
        return RiskAssessment(
            task_id=node.task_id,
            risk_level=RiskLevel.LOW,
            requires_approval=False,
            reason="Read-only or non-destructive operation.",
            action_summary=f"Read/Inspect: {node.title}"
        )

    async def check_and_authorize(
        self,
        node: TaskNode,
        hitl_callback: Optional[Callable[[ApprovalRequest], Awaitable[bool]]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Evaluates risk and budget. If approval is required, requests user confirmation.
        Returns (is_authorized, rejection_reason).
        """
        # 1. Check budget limits
        budget_ok, budget_err = self.budget.check_budget()
        if not budget_ok:
            logger.error(f"Execution blocked by budget circuit breaker: {budget_err}")
            return False, budget_err

        # 2. Evaluate risk
        assessment = self.evaluate_node(node)
        node.risk_level = assessment.risk_level

        # 3. Check if explicit HITL authorization is required
        if assessment.requires_approval:
            logger.warning(f"Task '{node.task_id}' requires HITL approval: {assessment.reason}")
            
            # Check if auto_confirm is enabled in environment or settings
            if self.security_manager and hasattr(self.security_manager, "is_auto_confirm_enabled"):
                if self.security_manager.is_auto_confirm_enabled():
                    logger.info("Auto-confirm is enabled in settings. Proceeding with caution.")
                    return True, None

            req = ApprovalRequest(
                action_id=node.task_id,
                tool_name=node.tool_name or "system",
                risk_level=ApprovalRiskLevel(assessment.risk_level.value),
                description=assessment.action_summary,
                params=node.args
            )

            callback = hitl_callback or self.approval_engine.hitl_callback
            if callback:
                try:
                    approved = await callback(req)
                    if not approved:
                        return False, f"User rejected authorization for: {assessment.action_summary}"
                    return True, None
                except Exception as e:
                    logger.exception(f"Error during HITL approval callback: {e}")
                    return False, f"Approval callback error: {e}"
            else:
                logger.warning("No HITL callback provided for critical task. Blocking by default.")
                return False, f"Requires user authorization: {assessment.action_summary}"

        return True, None
