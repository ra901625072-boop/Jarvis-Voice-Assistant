"""
capability_registry.py — Dynamic capability-based agent selection and load scoring.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import logging

logger = logging.getLogger("JARVIS.CapabilityRegistry")

@dataclass
class AgentCapability:
    agent_id: str
    task_types: Set[str]
    success_rate: Dict[str, float] = field(default_factory=dict)
    confidence: Dict[str, float] = field(default_factory=dict)
    current_load: int = 0
    total_executions: int = 0

class CapabilityRegistry:
    def __init__(self, w_success: float = 0.4, w_conf: float = 0.4, w_load: float = 0.2):
        self.w_success = w_success
        self.w_conf = w_conf
        self.w_load = w_load
        self._capabilities: Dict[str, AgentCapability] = {}
        self._register_defaults()

    def _register_defaults(self):
        # Register default capabilities for Jarvis agents
        self.register("planning_agent", {"create_plan", "replan"})
        self.register("coordinator_agent", {"execute_goal", "coordinate_flow", "select_agent"})
        self.register("verification_agent", {"verify_result", "verify_fix"})
        self.register("recovery_agent", {"recover_failure", "diagnose_error", "apply_self_healing"})
        self.register("research_agent", {"retrieve_context", "design_research"})
        self.register("coding_agent", {"write_code", "refactor_code", "build_project"})
        self.register("browser_agent", {"automate_web_flow", "call_api"})
        self.register("vision_agent", {"analyze_screen", "find_ui_element", "read_screen_text", "diff_screen_state"})
        self.register("interaction_agent", {"run_grounded_task", "locate_ordinal_element", "count_visible_items"})

        self.register("language_agent", {"detect_language", "translate_text", "extract_document_data"})
        self.register("memory_agent", {"store_episodic", "record_execution_report", "run_maintenance"})
        self.register("ui_ux_agent", {
            "design_review", "generate_wireframe", "generate_hifi_spec",
            "audit_accessibility", "generate_design_tokens", "design_research",
            "generate_component", "generate_prototype", "generate_svg_asset",
            "export_tokens", "calculate_contrast"
        })

    def register(self, agent_id: str, task_types: Set[str]):
        if agent_id in self._capabilities:
            self._capabilities[agent_id].task_types.update(task_types)
        else:
            self._capabilities[agent_id] = AgentCapability(agent_id=agent_id, task_types=set(task_types))

    def update_metrics(self, agent_id: str, task_type: str, success: bool, confidence: float):
        cap = self._capabilities.get(agent_id)
        if not cap:
            return

        cap.total_executions += 1
        # Exponential moving average for success rate
        prev_sr = cap.success_rate.get(task_type, 0.8)
        new_sr = prev_sr * 0.8 + (1.0 if success else 0.0) * 0.2
        cap.success_rate[task_type] = round(new_sr, 4)

        prev_conf = cap.confidence.get(task_type, 0.8)
        new_conf = prev_conf * 0.8 + confidence * 0.2
        cap.confidence[task_type] = round(new_conf, 4)

    def select_agent(self, task_type: str, default_agent: str = "coordinator_agent") -> str:
        candidates = [
            cap for cap in self._capabilities.values()
            if task_type in cap.task_types
        ]

        if not candidates:
            logger.debug(f"No registered agent for task_type '{task_type}'. Defaulting to '{default_agent}'.")
            return default_agent

        def score(cap: AgentCapability) -> float:
            sr = cap.success_rate.get(task_type, 0.8)
            conf = cap.confidence.get(task_type, 0.8)
            load = min(1.0, cap.current_load / 10.0)
            return (self.w_success * sr) + (self.w_conf * conf) - (self.w_load * load)

        best = max(candidates, key=score)
        return best.agent_id
