import logging
from typing import Dict, Any, List
from modules.core.state_manager import AgentStateManager, AgentState

logger = logging.getLogger("JARVIS.ExecutiveController")

class ExecutiveController:
    """
    The highest-level orchestration layer for JARVIS.
    Supervises goals, manages execution state transitions, and resolves conflicts.
    """
    def __init__(self, memory_manager, cognitive_coordinator=None):
        self.mm = memory_manager
        self.coordinator = cognitive_coordinator
        self.state_manager = AgentStateManager()
        
    def evaluate_system_readiness(self) -> str:
        """
        Check if the system is ready for execution, summarizing goals, resources, and state.
        """
        state = self.state_manager.agent_state
        if state in [AgentState.RECOVERING, AgentState.REPLANNING]:
            return "WARNING: Agent is currently recovering from a failure. Do not start new goals."
            
        if not hasattr(self.mm, 'lifecycle'):
            return "System READY (Lifecycle memory unavailable)."
            
        goals = self.mm.lifecycle.goal_memory.get_active_goals()
        if not goals:
            return "System IDLE. Ready for new user goals."
            
        top_goal = goals[0]
        return f"System READY. Top priority goal: '{top_goal['goal']}' (Priority {top_goal['priority']})."
        
    def resolve_conflicts(self) -> str:
        """
        Identify if there are competing active goals or stuck states, and resolve them.
        """
        state = self.state_manager.agent_state
        
        # Conflict 1: Agent stuck in EXECUTING but plan is empty/completed
        if state == AgentState.EXECUTING:
            plan = self.state_manager.active_plan
            if not plan or plan.status != "active":
                self.state_manager.set_agent_state(AgentState.IDLE)
                return "Resolved stuck execution state (reset to IDLE)."
                
        # Conflict 2: Agent stuck in VERIFYING for too long
        # (Assuming verification is synchronous, if it's async we might need timeouts)
                
        return "No conflicts detected."

    def get_executive_summary(self) -> str:
        """
        Provides a high-level summary of exactly what the agent should be doing right now.
        This gives the LLM explicit instructions on how to prioritize its actions.
        """
        readiness = self.evaluate_system_readiness()
        conflict_res = self.resolve_conflicts()
        
        state_directive = ""
        state = self.state_manager.agent_state
        
        if state == AgentState.IDLE:
            state_directive = "Directive: Wait for user input or pick up the top priority goal."
        elif state == AgentState.PLANNING:
            state_directive = "Directive: Generate a step-by-step plan using create_plan."
        elif state == AgentState.EXECUTING:
            state_directive = "Directive: Fetch the next task via get_next_task and execute it."
        elif state == AgentState.VERIFYING:
            state_directive = "Directive: Wait for verification results."
        elif state == AgentState.RECOVERING:
            state_directive = "Directive: Execute the deterministic recovery steps."
        elif state == AgentState.REPLANNING:
            state_directive = "Directive: Analyze the failure and generate a new plan."
            
        return (
            f"--- EXECUTIVE SUMMARY ---\n"
            f"State: {state.value}\n"
            f"Readiness: {readiness}\n"
            f"Conflicts: {conflict_res}\n"
            f"{state_directive}\n"
        )
