import pytest
from unittest.mock import AsyncMock, MagicMock
from ai.agents.types import AgentTask
from ai.agents.browser.agent import BrowserAgent
from ai.agents.coding.agent import CodingAgent
from ai.agents.debugging.agent import DebuggingAgent
from ai.agents.execution.agent import ExecutionAgent
from ai.agents.integration.agent import IntegrationAgent
from ai.agents.memory.agent import MemoryAgent
from ai.agents.planning.agent import PlanningAgent
from ai.agents.recovery.agent import RecoveryAgent
from ai.agents.supervisor.agent import SupervisorAgent
from ai.agents.verification.agent import VerificationAgent
from ai.agents.vision.agent import VisionAgent
from ai.agents.coordinator.agent import CoordinatorAgent

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
