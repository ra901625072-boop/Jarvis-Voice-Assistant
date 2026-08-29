import pytest
from modules.planning.task_graph import TaskGraph, TaskNode, TaskStatus, RiskLevel
from modules.planning.replanner import Replanner, ErrorCategory, ReplanStrategy, FailureDiagnosis

def test_diagnose_transient_error():
    replanner = Replanner()
    node = TaskNode(task_id="1", title="Fetch API", max_retries=3, attempt_count=0)
    
    diag = replanner.diagnose_failure(node, "Connection timed out (ReadTimeoutError)")
    assert diag.category == ErrorCategory.TRANSIENT
    assert diag.recommended_strategy == ReplanStrategy.LOCAL_RETRY
    assert diag.can_retry is True
    assert diag.retry_delay_seconds == 1.0

def test_diagnose_transient_error_exhausted_retries():
    replanner = Replanner()
    node = TaskNode(task_id="1", title="Fetch API", max_retries=2, attempt_count=2)
    
    diag = replanner.diagnose_failure(node, "503 Service Unavailable")
    assert diag.category == ErrorCategory.TRANSIENT
    assert diag.recommended_strategy == ReplanStrategy.SUBTREE_REPLAN
    assert diag.can_retry is False

def test_diagnose_permission_error():
    replanner = Replanner()
    node = TaskNode(task_id="1", title="Delete System Directory")
    
    diag = replanner.diagnose_failure(node, "Permission denied: access forbidden by security policy")
    assert diag.category == ErrorCategory.PERMISSION_DENIED
    assert diag.recommended_strategy == ReplanStrategy.ESCALATE
    assert diag.can_retry is False

def test_diagnose_resource_not_found():
    replanner = Replanner()
    node = TaskNode(task_id="1", title="Read Config File")
    
    diag = replanner.diagnose_failure(node, "FileNotFoundError: config.json not found")
    assert diag.category == ErrorCategory.RESOURCE_NOT_FOUND
    assert diag.recommended_strategy == ReplanStrategy.SUBTREE_REPLAN
    assert diag.can_retry is True

def test_apply_recovery_local_retry():
    replanner = Replanner()
    graph = TaskGraph(goal="Test Retry")
    node = TaskNode(task_id="1", title="Task 1", status=TaskStatus.FAILED)
    graph.add_node(node)
    
    diag = FailureDiagnosis(
        category=ErrorCategory.TRANSIENT,
        root_cause="Timeout",
        recommended_strategy=ReplanStrategy.LOCAL_RETRY
    )
    
    updated_graph, strategy = replanner.apply_recovery(graph, "1", diag)
    assert strategy == ReplanStrategy.LOCAL_RETRY
    assert updated_graph.get_node("1").status == TaskStatus.READY
    assert updated_graph.get_node("1").attempt_count == 1

def test_apply_recovery_subtree_grafting():
    replanner = Replanner()
    # 1 -> 2 -> 3
    graph = TaskGraph(goal="Graft Recovery Subtree")
    graph.add_node(TaskNode(task_id="1", title="Init", status=TaskStatus.COMPLETED))
    graph.add_node(TaskNode(task_id="2", title="Read File", dependencies=["1"], status=TaskStatus.FAILED))
    graph.add_node(TaskNode(task_id="3", title="Process File", dependencies=["2"], status=TaskStatus.PENDING))
    
    # Prerequisite recovery node: Create Default Config
    recovery_node = TaskNode(task_id="1.5", title="Create Default Config", dependencies=["1"])
    
    diag = FailureDiagnosis(
        category=ErrorCategory.RESOURCE_NOT_FOUND,
        root_cause="File missing",
        recommended_strategy=ReplanStrategy.SUBTREE_REPLAN
    )
    
    updated_graph, strategy = replanner.apply_recovery(graph, "2", diag, recovery_nodes=[recovery_node])
    assert strategy == ReplanStrategy.SUBTREE_REPLAN
    
    # Task 3 was invalidated
    assert updated_graph.get_node("3").status == TaskStatus.INVALIDATED
    # Recovery node added
    assert updated_graph.get_node("1.5") is not None
    # Task 2 re-wired to depend on recovery node 1.5
    assert "1.5" in updated_graph.get_node("2").dependencies
    assert updated_graph.get_node("2").status == TaskStatus.READY
    
    # Verify graph remains a valid DAG
    sorted_nodes = updated_graph.topological_sort()
    sorted_ids = [n.task_id for n in sorted_nodes]
    assert sorted_ids == ["1", "1.5", "2", "3"]
