import pytest
from modules.planning.task_graph import TaskGraph, TaskNode, TaskStatus, RiskLevel
from modules.task.state_manager import SubTask

def test_task_node_initialization_and_dict():
    node = TaskNode(
        task_id="1",
        title="Analyze Requirements",
        description="Extract core constraints",
        agent="research_agent",
        tool_name="web_search",
        args={"query": "black hole facts"},
        dependencies=[],
        expected_outputs=["research_notes.md"],
        definition_of_done=["Found 3 peer reviewed sources"],
        risk_level=RiskLevel.LOW
    )
    assert node.task_id == "1"
    assert node.status == TaskStatus.PENDING
    assert node.risk_level == RiskLevel.LOW
    
    d = node.to_dict()
    assert d["task_id"] == "1"
    assert d["status"] == "pending"
    assert d["risk_level"] == "low"
    
    rebuilt = TaskNode.from_dict(d)
    assert rebuilt.task_id == node.task_id
    assert rebuilt.title == node.title
    assert rebuilt.risk_level == RiskLevel.LOW

def test_task_graph_topological_sort_linear():
    graph = TaskGraph(goal="Linear Workflow")
    n1 = TaskNode(task_id="1", title="Step 1")
    n2 = TaskNode(task_id="2", title="Step 2", dependencies=["1"])
    n3 = TaskNode(task_id="3", title="Step 3", dependencies=["2"])
    
    graph.add_node(n2)
    graph.add_node(n1)
    graph.add_node(n3)
    
    sorted_nodes = graph.topological_sort()
    assert [n.task_id for n in sorted_nodes] == ["1", "2", "3"]

def test_task_graph_diamond_dependencies():
    # Diamond: 1 -> 2, 3 -> 4
    graph = TaskGraph(goal="Diamond Workflow")
    graph.add_node(TaskNode(task_id="1", title="Init"))
    graph.add_node(TaskNode(task_id="2", title="Backend", dependencies=["1"]))
    graph.add_node(TaskNode(task_id="3", title="Frontend", dependencies=["1"]))
    graph.add_node(TaskNode(task_id="4", title="Integration", dependencies=["2", "3"]))
    
    sorted_nodes = graph.topological_sort()
    ids = [n.task_id for n in sorted_nodes]
    assert ids[0] == "1"
    assert set(ids[1:3]) == {"2", "3"}
    assert ids[3] == "4"

def test_task_graph_cycle_detection():
    graph = TaskGraph(goal="Cycle Test")
    graph.add_node(TaskNode(task_id="1", title="A", dependencies=["3"]))
    graph.add_node(TaskNode(task_id="2", title="B", dependencies=["1"]))
    graph.add_node(TaskNode(task_id="3", title="C", dependencies=["2"]))
    
    with pytest.raises(ValueError, match="Circular dependency detected"):
        graph.topological_sort()

def test_task_graph_missing_dependency():
    graph = TaskGraph(goal="Missing Dep Test")
    graph.add_node(TaskNode(task_id="1", title="A", dependencies=["999"]))
    
    with pytest.raises(ValueError, match="depends on non-existent Task '999'"):
        graph.validate()

def test_task_graph_parallel_layers():
    graph = TaskGraph(goal="Parallel Phases")
    graph.add_node(TaskNode(task_id="1", title="Phase 0 - A"))
    graph.add_node(TaskNode(task_id="2", title="Phase 0 - B"))
    graph.add_node(TaskNode(task_id="3", title="Phase 1 - A", dependencies=["1"]))
    graph.add_node(TaskNode(task_id="4", title="Phase 1 - B", dependencies=["1", "2"]))
    graph.add_node(TaskNode(task_id="5", title="Phase 2 - Final", dependencies=["3", "4"]))
    
    layers = graph.get_parallel_layers()
    assert len(layers) == 3
    layer0_ids = {n.task_id for n in layers[0]}
    layer1_ids = {n.task_id for n in layers[1]}
    layer2_ids = {n.task_id for n in layers[2]}
    
    assert layer0_ids == {"1", "2"}
    assert layer1_ids == {"3", "4"}
    assert layer2_ids == {"5"}

def test_task_graph_ready_nodes_and_status():
    graph = TaskGraph(goal="Execution Ready Nodes")
    n1 = TaskNode(task_id="1", title="Task 1")
    n2 = TaskNode(task_id="2", title="Task 2", dependencies=["1"])
    n3 = TaskNode(task_id="3", title="Task 3", dependencies=["1"])
    
    graph.add_node(n1)
    graph.add_node(n2)
    graph.add_node(n3)
    
    # Initially only n1 is ready
    ready = graph.get_ready_nodes()
    assert len(ready) == 1
    assert ready[0].task_id == "1"
    
    # Complete n1
    graph.update_node_status("1", TaskStatus.COMPLETED, result="Done 1")
    
    ready = graph.get_ready_nodes()
    assert len(ready) == 2
    assert {n.task_id for n in ready} == {"2", "3"}

def test_task_graph_subtree_invalidation():
    # 1 -> 2 -> 4
    # 1 -> 3 -> 5
    graph = TaskGraph(goal="Subtree Invalidation")
    graph.add_node(TaskNode(task_id="1", title="T1"))
    graph.add_node(TaskNode(task_id="2", title="T2", dependencies=["1"]))
    graph.add_node(TaskNode(task_id="3", title="T3", dependencies=["1"]))
    graph.add_node(TaskNode(task_id="4", title="T4", dependencies=["2"]))
    graph.add_node(TaskNode(task_id="5", title="T5", dependencies=["3"]))
    
    # Invalidate subtree under T2 (should invalidate T2 and T4, but NOT T1, T3, T5)
    invalidated = graph.invalidate_subtree("2", include_root=True)
    assert set(invalidated) == {"2", "4"}
    assert graph.get_node("2").status == TaskStatus.INVALIDATED
    assert graph.get_node("4").status == TaskStatus.INVALIDATED
    assert graph.get_node("1").status == TaskStatus.PENDING
    assert graph.get_node("3").status == TaskStatus.PENDING
    assert graph.get_node("5").status == TaskStatus.PENDING

def test_legacy_subtask_interoperability():
    subtask = SubTask(
        description="Test legacy subtask",
        task_id=101,
        tool_name="execute_command",
        dependencies=[100],
        args={"command": "dir"}
    )
    
    node = TaskNode.from_legacy_subtask(subtask)
    assert node.task_id == "101"
    assert node.dependencies == ["100"]
    assert node.tool_name == "execute_command"
    assert node.args == {"command": "dir"}
    
    converted_back = node.to_legacy_subtask()
    assert converted_back.id == 101
    assert converted_back.dependencies == [100]
    assert converted_back.description == "Test legacy subtask"
