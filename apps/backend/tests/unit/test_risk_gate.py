import pytest
import asyncio
from modules.planning.task_graph import TaskNode, RiskLevel
from modules.planning.risk_gate import RiskGate, PlanningBudget, RiskAssessment
from modules.approval.engine import ApprovalRequest

def test_evaluate_node_low_risk():
    gate = RiskGate()
    node = TaskNode(
        task_id="1",
        title="Search Documentation",
        tool_name="web_search",
        args={"query": "FastAPI background tasks"}
    )
    assessment = gate.evaluate_node(node)
    assert assessment.risk_level == RiskLevel.LOW
    assert assessment.requires_approval is False

def test_evaluate_node_medium_risk():
    gate = RiskGate()
    node = TaskNode(
        task_id="2",
        title="Create App Router",
        tool_name="create_file",
        args={"path": "routes.py", "content": "from fastapi import APIRouter"}
    )
    assessment = gate.evaluate_node(node)
    assert assessment.risk_level == RiskLevel.MEDIUM
    assert assessment.requires_approval is False

def test_evaluate_node_critical_risk_deletion():
    gate = RiskGate()
    node = TaskNode(
        task_id="3",
        title="Delete User Data Directory",
        tool_name="delete_directory",
        args={"path": "d:/Jarvis/data/users"}
    )
    assessment = gate.evaluate_node(node)
    assert assessment.risk_level == RiskLevel.CRITICAL
    assert assessment.requires_approval is True

def test_evaluate_node_critical_risk_shell_pattern():
    gate = RiskGate()
    node = TaskNode(
        task_id="4",
        title="Clean up disk",
        tool_name="execute_command",
        args={"command": "rm -rf /tmp/data"}
    )
    assessment = gate.evaluate_node(node)
    assert assessment.risk_level == RiskLevel.CRITICAL
    assert assessment.requires_approval is True

def test_planning_budget_tool_limit():
    budget = PlanningBudget(max_tool_invocations=3)
    
    budget.record_tool_call()
    budget.record_tool_call()
    ok, err = budget.check_budget()
    assert ok is True
    assert err is None
    
    budget.record_tool_call()
    ok, err = budget.check_budget()
    assert ok is False
    assert "Maximum tool invocations reached" in err

def test_planning_budget_cost_limit():
    budget = PlanningBudget(max_cost_usd=1.0)
    budget.record_tool_call(tokens=500, cost_usd=0.60)
    ok, _ = budget.check_budget()
    assert ok is True
    
    budget.record_tool_call(tokens=500, cost_usd=0.50)
    ok, err = budget.check_budget()
    assert ok is False
    assert "cost budget exceeded" in err

@pytest.mark.asyncio
async def test_check_and_authorize_hitl_approval():
    async def mock_hitl_allow(req: ApprovalRequest) -> bool:
        return True

    gate = RiskGate()
    node = TaskNode(
        task_id="5",
        title="Delete Database",
        tool_name="delete_file",
        args={"path": "db.sqlite3"}
    )
    
    auth, err = await gate.check_and_authorize(node, hitl_callback=mock_hitl_allow)
    assert auth is True
    assert err is None

@pytest.mark.asyncio
async def test_check_and_authorize_hitl_rejection():
    async def mock_hitl_deny(req: ApprovalRequest) -> bool:
        return False

    gate = RiskGate()
    node = TaskNode(
        task_id="6",
        title="Drop Database Tables",
        tool_name="execute_command",
        args={"command": "drop database production;"}
    )
    
    auth, err = await gate.check_and_authorize(node, hitl_callback=mock_hitl_deny)
    assert auth is False
    assert "User rejected authorization" in err
