import pytest
from unittest.mock import AsyncMock, MagicMock
from ai.agents.coding.agent import CodingAgent
from ai.agents.types import AgentTask

@pytest.mark.asyncio
async def test_write_code_success():
    bus = MagicMock()
    bus.register = MagicMock()
    agent = CodingAgent(bus=bus)
    agent.generate_response = AsyncMock(return_value='{"file_path":"main.py","content":"print(1)","explanation":"test"}')

    task = AgentTask(task_id="t1", task_type="write_code", target_agent="coding_agent", origin_agent="test",
                     payload={"instruction": "Print 1", "file_path": "main.py"})
    result = await agent.handle(task)

    assert result.success is True
    assert result.result["file_path"] == "main.py"

@pytest.mark.asyncio
async def test_unknown_task_type():
    bus = MagicMock()
    bus.register = MagicMock()
    agent = CodingAgent(bus=bus)
    task = AgentTask(task_id="t2", task_type="unknown_type", target_agent="coding_agent", origin_agent="test", payload={})
    result = await agent.handle(task)
    assert result.success is False
    assert "does not support" in result.error
