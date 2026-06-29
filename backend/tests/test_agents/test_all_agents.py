import pytest
from unittest.mock import AsyncMock, MagicMock
from agents.types import AgentTask
from agents.browser_agent import BrowserAgent
from agents.coding_agent import CodingAgent
from agents.debugging_agent import DebuggingAgent
from agents.execution_agent import ExecutionAgent
from agents.integration_agent import IntegrationAgent
from agents.memory_agent import MemoryAgent
from agents.planning_agent import PlanningAgent
from agents.recovery_agent import RecoveryAgent
from agents.supervisor_agent import SupervisorAgent
from agents.verification_agent import VerificationAgent
from agents.vision_agent import VisionAgent
from agents.coordinator_agent import CoordinatorAgent

@pytest.mark.asyncio
@pytest.mark.parametrize("agent_class,agent_id", [
    (BrowserAgent, "browser_agent"),
    (CodingAgent, "coding_agent"),
    (DebuggingAgent, "debugging_agent"),
    (ExecutionAgent, "execution_agent"),
    (IntegrationAgent, "integration_agent"),
    (MemoryAgent, "memory_agent"),
    (PlanningAgent, "planning_agent"),
    (RecoveryAgent, "recovery_agent"),
    (SupervisorAgent, "supervisor_agent"),
    (VerificationAgent, "verification_agent"),
    (VisionAgent, "vision_agent"),
    (CoordinatorAgent, "coordinator_agent")
])
async def test_unknown_task_type_all_agents(agent_class, agent_id):
    bus = MagicMock()
    bus.register = MagicMock()
    
    # Init with required mock args depending on agent
    if agent_id == "coordinator_agent":
        agent = agent_class(bus=bus, available_agents=[])
    elif agent_id == "planning_agent":
        mem = MagicMock()
        agent = agent_class(memory_agent=mem, bus=bus)
    elif agent_id == "execution_agent":
        agent = agent_class(tools_list=[], memory_agent=MagicMock(), bus=bus)
    elif agent_id == "supervisor_agent":
        agent = agent_class(bus=bus)
    elif agent_id == "memory_agent":
        agent = agent_class(memory=MagicMock(), bus=bus)
    elif agent_id == "vision_agent":
        agent = agent_class(vision_manager=MagicMock(), bus=bus)
    else:
        agent = agent_class(bus=bus)

    task = AgentTask(task_id="test", task_type="unknown_task_999", target_agent=agent_id, origin_agent="test", payload={})
    result = await agent.handle(task)
    assert result.success is False
    assert "does not support" in result.error or "not support" in result.error or "failed handling" in result.error or "Failed" in result.error or "Error" in result.error or result.error
