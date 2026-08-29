"""
root_cause_analyzer.py
----------------------
Deep causal failure analysis for agent execution trajectories.
Classifies root causes beyond regex clustering and extracts operational invariants.
"""

import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("JARVIS.RootCauseAnalyzer")


class RootCauseAnalyzer:
    """
    Analyzes failed episodes to identify the structural root cause and formulate invariant rules.
    """

    CATEGORIES = {
        "invariant_violation": [
            r"kill.*server",
            r"close.*dashboard",
            r"close.*infrastructure",
            r"delete.*root",
            r"terminate.*daemon",
            r"invariant",
        ],
        "tool_argument_error": [
            r"missing required argument",
            r"invalid argument",
            r"validation error",
            r"jsondecodeerror",
            r"typeerror",
            r"valueerror",
        ],
        "environment_state_error": [
            r"not found|404|no such file",
            r"connection.?refused|econnrefused",
            r"port.*already in use",
            r"session closed|tab closed",
            r"element not found|no such element",
        ],
        "timeout_or_latency_error": [
            r"timed out|timeout",
            r"deadline exceeded",
            r"gateway timeout|504",
            r"cold.?start",
        ],
        "rate_limit_or_captcha_error": [
            r"captcha",
            r"cloudflare",
            r"rate.?limit|429|too many requests",
            r"quota exceeded",
        ],
        "permission_or_security_error": [
            r"permission.?denied|access.?denied|403",
            r"unauthorized|401",
            r"security.*block",
        ],
        "planning_logic_error": [
            r"max iterations|infinite loop",
            r"circular dependency",
            r"no plan resolved",
            r"precondition failed",
        ],
    }

    def analyze(self, episode: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes a failed episode and returns a structured diagnosis with preventative invariants.
        """
        error = str(episode.get("outcome", {}).get("error") or "")
        task_type = episode.get("task_type", "task")
        agent_id = episode.get("agent_id", "agent")
        goal = episode.get("goal", "")
        trajectory = episode.get("trajectory", [])

        # Check trajectory steps for additional error details
        step_errors = [s.get("error") for s in trajectory if s.get("error")]
        full_error_text = f"{error} {' '.join(str(e) for e in step_errors)}".lower()

        matched_category = "unclassified_failure"
        for category, patterns in self.CATEGORIES.items():
            for pat in patterns:
                if re.search(pat, full_error_text):
                    matched_category = category
                    break
            if matched_category != "unclassified_failure":
                break

        # Derive invariant rules and actionable preventative guidance
        invariant_rule = self._derive_invariant_rule(matched_category, agent_id, task_type, goal)
        preventative_guidance = self._derive_preventative_guidance(matched_category, task_type)

        analysis = {
            "root_cause_category": matched_category,
            "error_summary": error[:200],
            "invariant_rule": invariant_rule,
            "preventative_guidance": preventative_guidance,
            "confidence": 0.85 if matched_category != "unclassified_failure" else 0.50,
        }

        return analysis

    def _derive_invariant_rule(self, category: str, agent_id: str, task_type: str, goal: str) -> Optional[str]:
        if category == "invariant_violation":
            return "Infrastructure-critical resources and server processes must never be terminated during task execution without explicit user authorization."
        elif category == "environment_state_error":
            return f"Verify prerequisite system state, active tabs, and dependencies before executing '{task_type}' actions."
        elif category == "timeout_or_latency_error":
            return "Do not couple initial execution to synchronous external service availability; use retry backoff and asynchronous polling."
        elif category == "rate_limit_or_captcha_error":
            return "When external rate limits or challenges are encountered, pause execution and use cached data or alternative sources rather than aggressive retries."
        elif category == "tool_argument_error":
            return f"Ensure strict parameter validation and schema compliance before invoking tools in '{task_type}'."
        return None

    def _derive_preventative_guidance(self, category: str, task_type: str) -> str:
        guidance_map = {
            "invariant_violation": "Enforce strict isolation between task temporary processes and persistent host infrastructure.",
            "tool_argument_error": "Sanitize and validate all JSON arguments against the tool schema prior to dispatch.",
            "environment_state_error": "Perform pre-flight environmental checks (directory presence, active connection, open port) before execution.",
            "timeout_or_latency_error": "Increase timeout thresholds, implement exponential backoff, and poll health endpoints asynchronously.",
            "rate_limit_or_captcha_error": "Throttle request velocity and employ fallback proxy/headers or cached responses.",
            "permission_or_security_error": "Check operation permissions prior to write/modify actions; request elevated credentials if required.",
            "planning_logic_error": "Deconstruct task into smaller atomic steps and verify milestone progress after each step.",
            "unclassified_failure": "Log full execution context and apply alternative strategy upon retry.",
        }
        return guidance_map.get(category, "Apply alternative strategy upon retry.")
