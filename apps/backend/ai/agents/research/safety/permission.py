"""
apps/backend/ai/agents/research/safety/permission.py
Budget Enforcement and Resource Guardrails for Autonomous Research Loops.
"""
import time
import logging
from typing import Tuple

from ai.agents.research.schemas.research import ResearchBudget

logger = logging.getLogger("JARVIS.ResearchSafety.BudgetGuard")


class ResearchBudgetGuard:
    """
    Tracks and enforces resource ceilings for deep research tasks to prevent runaway loops or unbounded costs.
    """

    def __init__(self, budget: ResearchBudget):
        self.budget = budget
        self.start_time = time.time()
        self.iteration_count = 0
        self.search_count = 0
        self.sources_fetched_count = 0
        self.tokens_used = 0
        self.estimated_cost_usd = 0.0

    def record_iteration(self) -> None:
        self.iteration_count += 1

    def record_search(self, count: int = 1) -> None:
        self.search_count += count

    def record_source_fetch(self, count: int = 1) -> None:
        self.sources_fetched_count += count

    def record_tokens(self, tokens: int, cost_rate_per_1k: float = 0.0005) -> None:
        self.tokens_used += tokens
        self.estimated_cost_usd += (tokens / 1000.0) * cost_rate_per_1k

    def check_limits(self) -> Tuple[bool, str]:
        """
        Evaluates whether research is within budget or if a limit was exceeded.
        Returns (within_budget, reason_if_exceeded).
        """
        elapsed_seconds = time.time() - self.start_time

        if self.iteration_count >= self.budget.max_iterations:
            return False, f"Iteration ceiling reached ({self.iteration_count}/{self.budget.max_iterations})"

        if self.search_count >= self.budget.max_searches:
            return False, f"Search query ceiling reached ({self.search_count}/{self.budget.max_searches})"

        if self.sources_fetched_count >= self.budget.max_sources:
            return False, f"Source ingestion ceiling reached ({self.sources_fetched_count}/{self.budget.max_sources})"

        if elapsed_seconds >= self.budget.max_runtime_seconds:
            return False, f"Runtime limit exceeded ({elapsed_seconds:.1f}s / {self.budget.max_runtime_seconds}s)"

        if self.tokens_used >= self.budget.max_tokens:
            return False, f"Token ceiling reached ({self.tokens_used}/{self.budget.max_tokens})"

        if self.estimated_cost_usd >= self.budget.max_cost_usd:
            return False, f"Cost budget exceeded (${self.estimated_cost_usd:.2f} / ${self.budget.max_cost_usd:.2f})"

        return True, "OK"
