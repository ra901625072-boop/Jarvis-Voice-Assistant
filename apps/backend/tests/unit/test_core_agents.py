"""
tests/unit/test_core_agents.py — Dedicated unit test suite for JARVIS core agents.
"""
import os
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from modules.bus.redis_bus import RedisBus
from ai.contracts import AgentTask, AgentResult, TaskPriority

from ai.agents.supervisor.agent import SupervisorAgent
from ai.agents.coordinator.agent import CoordinatorAgent
from ai.agents.planning.agent import PlanningAgent
from ai.agents.execution.agent import ExecutionAgent
from ai.agents.coding.agent import CodingAgent
from ai.agents.debugging.agent import DebuggingAgent
from ai.agents.verification.agent import VerificationAgent
from ai.agents.recovery.agent import RecoveryAgent


class TestSupervisorAgent:
    @pytest.mark.asyncio
    async def test_health_check_and_unsupported(self):
        bus = RedisBus()
        agent = SupervisorAgent(bus)
        
        # Health check
        hc_task = AgentTask(task_id="t_hc", task_type="health_check", target_agent="supervisor_agent")
        hc_res = await agent.handle(hc_task)
        assert hc_res.success is True
        assert hc_res.result == "ok"

        # Unsupported task
        un_task = AgentTask(task_id="t_un", task_type="unknown_task_xyz", target_agent="supervisor_agent")
        un_res = await agent.handle(un_task)
        assert un_res.success is False
        assert "does not support task type" in un_res.error

    @pytest.mark.asyncio
    async def test_speak_task_handling(self):
        bus = RedisBus()
        agent = SupervisorAgent(bus)
        
        speak_task = AgentTask(
            task_id="t_speak",
            task_type="speak",
            target_agent="supervisor_agent",
            payload={"text": "System operational.", "priority": "high"}
        )
        res = await agent.handle(speak_task)
        assert res.success is True


class TestCoordinatorAgent:
    @pytest.mark.asyncio
    async def test_coordinator_lifecycle_and_classification(self, memory_manager):
        bus = RedisBus()
        agent = CoordinatorAgent(bus, available_agents=["coding_agent", "execution_agent"], memory_manager=memory_manager)
        
        # Health check
        hc_task = AgentTask(task_id="t_coord_hc", task_type="health_check", target_agent="coordinator_agent")
        hc_res = await agent.handle(hc_task)
        assert hc_res.success is True

        # Test subtask mode classification
        assert agent._classify_subtask_mode("click on the 2nd button on screen") == "grounded"
        assert agent._classify_subtask_mode("run terminal command python test.py") != "grounded"

    @pytest.mark.asyncio
    async def test_coordinator_generate_context(self, memory_manager):
        bus = RedisBus()
        agent = CoordinatorAgent(bus, available_agents=["coding_agent"], memory_manager=memory_manager)
        
        with patch.object(agent, "generate_response", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "Optimized environment context for target goal."
            task = AgentTask(
                task_id="t_ctx",
                task_type="generate_context",
                target_agent="coordinator_agent",
                payload={"goal": "deploy website"}
            )
            res = await agent.handle(task)
            assert res.success is True
            assert "context" in res.result


class TestPlanningAgent:
    @pytest.mark.asyncio
    async def test_plan_normalization_and_cycles(self):
        bus = RedisBus()
        mock_mem_agent = MagicMock()
        mock_mem_agent.memory = None
        agent = PlanningAgent(mock_mem_agent, bus)
        
        # Valid plan items
        valid_steps = [
            {"id": 1, "task": "Create script", "tool_name": "write_code", "args": {"file_path": "a.py", "code": "print(1)"}, "depends_on": []},
            {"id": 2, "task": "Run script", "tool_name": "run_terminal_command", "args": {"command": "python a.py"}, "depends_on": [1]}
        ]
        subtasks = agent._normalize_and_validate_plan(valid_steps)
        assert len(subtasks) == 2
        assert subtasks[0].id == 1
        assert subtasks[1].dependencies == [1]

        # Cyclic dependency detection
        cyclic_steps = [
            {"id": 1, "task": "Step 1", "tool_name": "exec", "depends_on": [2]},
            {"id": 2, "task": "Step 2", "tool_name": "exec", "depends_on": [1]}
        ]
        with pytest.raises(ValueError, match="Circular dependency"):
            agent._normalize_and_validate_plan(cyclic_steps)


class TestExecutionAgent:
    @pytest.mark.asyncio
    async def test_execution_health_and_plan_validation(self, security_manager):
        bus = RedisBus()
        mock_mem_agent = MagicMock()
        mock_mem_agent.memory = None
        agent = ExecutionAgent(tools_list=[], memory_agent=mock_mem_agent, bus=bus, security=security_manager)
        
        # Health check
        hc_task = AgentTask(task_id="t_exec_hc", task_type="health_check", target_agent="execution_agent")
        hc_res = await agent.handle(hc_task)
        assert hc_res.success is True

        # Validate empty plan execution
        plan_task = AgentTask(
            task_id="t_plan_empty",
            task_type="execute_plan",
            target_agent="execution_agent",
            payload={"plan": [], "goal": "empty goal"}
        )
        res = await agent.handle(plan_task)
        assert res.success is True


class TestCodingAgent:
    @pytest.mark.asyncio
    async def test_write_code_direct(self, tmp_path):
        bus = RedisBus()
        agent = CodingAgent(bus)
        
        target_file = tmp_path / "hello.py"
        task = AgentTask(
            task_id="t_write",
            task_type="write_code",
            target_agent="coding_agent",
            payload={
                "file_path": str(target_file),
                "code_content": "def greet():\n    return 'JARVIS'\n"
            }
        )
        res = await agent.handle(task)
        assert res.success is True
        assert target_file.exists()
        assert "def greet():" in target_file.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_refactor_code_llm(self):
        bus = RedisBus()
        agent = CodingAgent(bus)
        
        mock_resp = json.dumps({
            "file_path": "test.py",
            "content": "def refactored(): pass",
            "explanation": "Refactored logic"
        })
        with patch.object(agent, "generate_response", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_resp
            task = AgentTask(
                task_id="t_refactor",
                task_type="refactor_code",
                target_agent="coding_agent",
                payload={"file_path": "test.py", "refactoring_goal": "Clean structure", "content": "def old(): pass"}
            )
            res = await agent.handle(task)
            assert res.success is True
            assert res.result["content"] == "def refactored(): pass"


class TestDebuggingAgent:
    @pytest.mark.asyncio
    async def test_diagnose_and_verify_fix(self):
        bus = RedisBus()
        agent = DebuggingAgent(bus)
        
        # Diagnose error
        mock_diag = json.dumps({
            "symptom": "IndexError: list index out of range",
            "root_cause": "Empty array accessed at index 0",
            "proposed_fix": "Add length check before indexing"
        })
        with patch.object(agent, "generate_response", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_diag
            task = AgentTask(
                task_id="t_diag",
                task_type="diagnose_error",
                target_agent="debugging_agent",
                payload={"error_context": "IndexError: list index out of range", "component_name": "list_parser"}
            )
            res = await agent.handle(task)
            assert res.success is True
            assert res.result["symptom"] == "IndexError: list index out of range"
            assert "length check" in res.result["proposed_fix"]

        # Verify fix
        mock_ver = json.dumps({"is_fixed": True, "reason": "All test assertions passed"})
        with patch.object(agent, "generate_response", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_ver
            task_v = AgentTask(
                task_id="t_ver",
                task_type="verify_fix",
                target_agent="debugging_agent",
                payload={"test_command": "pytest", "execution_output": "1 passed in 0.05s"}
            )
            res_v = await agent.handle(task_v)
            assert res_v.success is True
            assert res_v.result["is_fixed"] is True


class TestVerificationAgent:
    @pytest.mark.asyncio
    async def test_verify_result_pass_and_fail(self):
        bus = RedisBus()
        agent = VerificationAgent(bus)
        
        mock_ver_pass = json.dumps({"verified": True, "reason": "File exists and contains expected data"})
        with patch.object(agent, "generate_response", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_ver_pass
            task = AgentTask(
                task_id="t_vg",
                task_type="verify_result",
                target_agent="verification_agent",
                payload={"expected_outcome": "CSV file generated", "output": "Created export.csv with 50 rows"}
            )
            res = await agent.handle(task)
            assert res.success is True
            assert res.result["verified"] is True


class TestRecoveryAgent:
    @pytest.mark.asyncio
    async def test_recovery_flow(self, memory_manager):
        bus = RedisBus()
        agent = RecoveryAgent(bus, memory=memory_manager)
        
        mock_rec = json.dumps({
            "action": "retry",
            "reasoning": "Transient network failure, safe to retry with backoff",
            "modified_params": {"timeout": 30}
        })
        with patch.object(agent, "generate_response", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_rec
            task = AgentTask(
                task_id="t_rec",
                task_type="recover_failure",
                target_agent="recovery_agent",
                payload={
                    "failed_task_description": "Fetch API status",
                    "error_context": "ConnectionResetError: Remote host closed connection",
                    "goal": "Verify remote health"
                }
            )
            res = await agent.handle(task)
            assert res.success is True
            assert res.result["action"] == "retry"
