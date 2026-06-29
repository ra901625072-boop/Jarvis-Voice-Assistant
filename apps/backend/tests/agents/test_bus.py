import pytest
import asyncio
from agents.types import AgentTask, AgentResult, TaskPriority
from agents.bus import AgentBus

@pytest.fixture
def bus():
    return AgentBus()

@pytest.mark.asyncio
async def test_agent_bus_routing(bus):
    async def mock_handler(task: AgentTask) -> AgentResult:
        return AgentResult(task_id=task.task_id, success=True, result="handled")

    bus.register("mock_agent", mock_handler)
    
    task = AgentTask(
        task_id="t1",
        task_type="test",
        payload={},
        origin_agent="test_runner",
        target_agent="mock_agent"
    )
    
    result = await bus.dispatch(task)
    assert result.success is True
    assert result.result == "handled"
    assert result.task_id == "t1"

@pytest.mark.asyncio
async def test_agent_bus_no_handler(bus):
    task = AgentTask(
        task_id="t2",
        task_type="test",
        payload={},
        origin_agent="test_runner",
        target_agent="missing_agent"
    )
    
    result = await bus.dispatch(task)
    assert result.success is False
    assert "No handler registered" in result.error

@pytest.mark.asyncio
async def test_agent_bus_timeout(bus):
    async def slow_handler(task: AgentTask) -> AgentResult:
        await asyncio.sleep(0.5)
        return AgentResult(task_id=task.task_id, success=True, result="done")

    bus.register("slow_agent", slow_handler)
    
    task = AgentTask(
        task_id="t3",
        task_type="test",
        payload={},
        origin_agent="test_runner",
        target_agent="slow_agent",
        timeout_seconds=0.1
    )
    
    result = await bus.dispatch(task)
    assert result.success is False
    assert "timed out" in result.error

@pytest.mark.asyncio
async def test_agent_bus_exception(bus):
    async def error_handler(task: AgentTask) -> AgentResult:
        raise ValueError("Something went wrong")

    bus.register("error_agent", error_handler)
    
    task = AgentTask(
        task_id="t4",
        task_type="test",
        payload={},
        origin_agent="test_runner",
        target_agent="error_agent"
    )
    
    result = await bus.dispatch(task)
    assert result.success is False
    assert "Something went wrong" in result.error
