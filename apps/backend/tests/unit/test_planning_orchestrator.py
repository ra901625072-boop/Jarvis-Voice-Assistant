import pytest
from unittest.mock import MagicMock, AsyncMock
from ai.agents.planning.agent import PlanningAgent
from ai.agents.types import AgentTask, AgentResult
from modules.planning.task_graph import TaskGraph, TaskNode, TaskStatus, RiskLevel
from modules.planning.replanner import ErrorCategory, ReplanStrategy

class MockBus:
    def __init__(self):
        self.handlers = {}

    def register(self, agent_id, handler):
        self.handlers[agent_id] = handler

    async def dispatch(self, task: AgentTask) -> AgentResult:
        if task.target_agent in self.handlers:
            return await self.handlers[task.target_agent](task)
        return AgentResult(task_id=task.task_id, success=False, result=None, error="Agent not found")

class MockMemoryAgent:
    def __init__(self):
        self.memory = MagicMock()

@pytest.fixture
def planning_agent():
    bus = MockBus()
    memory_agent = MockMemoryAgent()
    agent = PlanningAgent(memory_agent, bus)
    return agent

@pytest.mark.asyncio
async def test_planning_agent_static_intent(planning_agent):
    task = AgentTask(
        task_id="t1",
        task_type="create_plan",
        payload={"goal": "open notepad"}
    )
    result = await planning_agent.handle(task)
    assert result.success is True
    assert "plan" in result.result
    assert "task_graph" in result.result
    assert result.result["task_graph"]["goal"] == "open notepad"

@pytest.mark.asyncio
async def test_planning_agent_create_task_graph(planning_agent):
    task = AgentTask(
        task_id="t2",
        task_type="create_task_graph",
        payload={"goal": "open notepad"}
    )
    result = await planning_agent.handle(task)
    assert result.success is True
    assert "task_graph" in result.result
    assert "layers" in result.result
    assert len(result.result["layers"]) >= 1

@pytest.mark.asyncio
async def test_planning_agent_evaluate_plan_risk(planning_agent):
    plan_payload = [
        {"id": "1", "task": "Search Documentation", "tool_name": "web_search", "args": {"query": "python"}},
        {"id": "2", "task": "Delete Temp Directory", "tool_name": "delete_directory", "args": {"path": "/tmp"}}
    ]
    task = AgentTask(
        task_id="t3",
        task_type="evaluate_plan_risk",
        payload={"plan": plan_payload}
    )
    result = await planning_agent.handle(task)
    assert result.success is True
    evals = result.result["evaluations"]
    assert len(evals) == 2
    assert evals[0]["risk_level"] == "low"
    assert evals[1]["risk_level"] == "critical"
    assert result.result["requires_overall_hitl"] is True

@pytest.mark.asyncio
async def test_planning_agent_diagnose_and_replan(planning_agent):
    graph = TaskGraph(goal="Test Replan Flow")
    graph.add_node(TaskNode(task_id="1", title="Fetch Data", tool_name="fetch_url"))
    
    task = AgentTask(
        task_id="t4",
        task_type="diagnose_and_replan",
        payload={
            "goal": "Test Replan Flow",
            "task_graph": graph.to_dict(),
            "failed_task": {"id": "1", "title": "Fetch Data"},
            "error": "Connection timed out (ReadTimeoutError)"
        }
    )
    result = await planning_agent.handle(task)
    assert result.success is True
    diag = result.result["diagnosis"]
    assert diag["category"] == ErrorCategory.TRANSIENT.value
    assert diag["strategy"] == ReplanStrategy.LOCAL_RETRY.value
    assert result.result["task_graph"]["nodes"]["1"]["status"] == "ready"
