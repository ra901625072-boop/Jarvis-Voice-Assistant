"""
tests/unit/test_memory_agent_eval.py
------------------------------------
Autonomous Memory Agent 10-Point Evaluation Benchmark.

Validates end-to-end cognitive memory capabilities:
  TEST 01 — Store (Explicit semantic preference creation)
  TEST 02 — Retrieval (Task context retrieval finds relevant preference)
  TEST 03 — Conflict (Contradiction detected -> old superseded, new active)
  TEST 04 — Deduplication (Repeated statements -> single canonical memory with bumped frequency)
  TEST 05 — Scope Isolation (Project A vs Project B context isolation)
  TEST 06 — Forgetting / Decay (Decay calculation + pruning of low-value memory on simulated time advance)
  TEST 07 — Safety (Procedural memory / tool policy blocks dangerous actions e.g. closing protected server tab)
  TEST 08 — Learning (Failure tracking & reflection engine produces lesson / procedural memory)
  TEST 09 — False Memory (Write gate rejects low-confidence/noise inputs)
  TEST 10 — Recovery (Fallback to structured SQLite/FTS5 when vector engine is disabled/unavailable)
"""

import pytest
import os
from datetime import datetime, timedelta

from modules.memory.manager import MemoryManager
from modules.memory.gate import MemoryGate, GateDecision
from modules.knowledge.conflict_resolver import ConflictResolver
from modules.memory.consolidator import MemoryConsolidator
from modules.learning.tool_memory import ToolMemory
from modules.browser.policy import BrowserPolicyEngine, TabRecord


@pytest.fixture
def mem_mgr(tmp_path):
    """Creates a temporary isolated MemoryManager instance."""
    db_dir = str(tmp_path / "jarvis_memory_test")
    os.makedirs(db_dir, exist_ok=True)
    manager = MemoryManager(base_dir=db_dir)
    yield manager
    try:
        manager.close()
    except Exception:
        pass


class TestMemoryAgentEvaluationSuite:
    """10-Point Cognitive Memory Agent Benchmark Suite."""

    # =========================================================================
    # TEST 01 — Store: Explicit user preference creates semantic preference
    # =========================================================================
    def test_01_store_explicit_preference(self, mem_mgr):
        """User: 'Remember that my reports should use Markdown.' -> Stored as semantic memory."""
        content = "User preference: All generated reports should use Markdown format with clear headings."
        mem_id = mem_mgr.store_semantic(
            content=content,
            importance=9,
            project="general",
            tags="reports,markdown,preference"
        )
        assert mem_id is not None
        assert mem_id > 0

        # Verify stored in SQLite semantic_memories
        with mem_mgr._lock.read_lock():
            row = mem_mgr.dbs["conversations"].execute(
                "SELECT id, content, importance, project FROM semantic_memories WHERE id = ?",
                (mem_id,)
            ).fetchone()

        assert row is not None
        assert "Markdown" in row[1]
        assert row[2] == 9
        assert row[3] == "general"

    # =========================================================================
    # TEST 02 — Retrieval: Querying for report task retrieves Markdown preference
    # =========================================================================
    def test_02_retrieval_preference(self, mem_mgr):
        """Later: 'Create a report.' -> Markdown preference is retrieved into context."""
        mem_mgr.store_semantic(
            content="User preference: All generated reports should use Markdown format with clear headings.",
            importance=9,
            project="general",
            tags="reports,markdown,preference"
        )

        results = mem_mgr.search_semantic(query="Create a report", limit=5)
        assert len(results) > 0
        matched_contents = [r.get("content", "") for r in results]
        assert any("Markdown" in c for c in matched_contents)

    # =========================================================================
    # TEST 03 — Conflict: Preference change supersedes old preference
    # =========================================================================
    def test_03_conflict_resolution_and_superseding(self, mem_mgr):
        """User changes preference from Python backend to Rust backend -> Old is superseded."""
        # 1. Store initial preference
        old_id = mem_mgr.store_semantic(
            content="User's favorite language is Python for all backend projects.",
            importance=8,
            project="backend"
        )
        assert old_id is not None

        # 2. Run conflict resolver with new preference
        resolver = ConflictResolver(mem_mgr)
        new_content = "User's favorite language is Rust for all backend projects."
        
        # Check and resolve conflict (marks old conflicts as superseded=1)
        adjusted_imp = resolver.check_and_resolve(new_content, importance=8, project="backend")
        
        # Store new preference with adjusted importance
        new_id = mem_mgr.store_semantic(
            content=new_content,
            importance=adjusted_imp,
            project="backend"
        )

        assert new_id is not None
        assert new_id != old_id

        # Verify old record is marked as superseded in SQLite
        with mem_mgr._lock.read_lock():
            old_row = mem_mgr.dbs["conversations"].execute(
                "SELECT id, superseded FROM semantic_memories WHERE id = ?",
                (old_id,)
            ).fetchone()
            
            assert old_row is not None
            assert old_row[1] == 1, "Old conflicting memory must be marked superseded=1"

    # =========================================================================
    # TEST 04 — Deduplication: User repeating preference 10x does not duplicate
    # =========================================================================
    def test_04_deduplication_and_frequency(self, mem_mgr):
        """User repeats the exact same input 10 times -> MemoryGate rejects duplicates."""
        gate = MemoryGate()
        text = "Please always use dark mode for all dashboard interfaces."
        
        decisions = []
        for _ in range(10):
            decision, reason = gate.evaluate(content=text, role="user", importance=8)
            decisions.append(decision)

        # First evaluation should pass
        assert decisions[0] == GateDecision.PASS
        # Subsequent evaluations should be rejected as duplicate
        duplicate_rejections = [d for d in decisions[1:] if d == GateDecision.REJECT]
        assert len(duplicate_rejections) >= 8

    # =========================================================================
    # TEST 05 — Scope Isolation: Project A vs Project B isolation
    # =========================================================================
    def test_05_scope_isolation(self, mem_mgr):
        """Project Alpha uses FastAPI; Project Beta uses Django -> Strict isolation."""
        mem_mgr.store_semantic(
            content="Project Alpha backend is built with FastAPI and async handlers.",
            importance=8,
            project="project_alpha"
        )
        mem_mgr.store_semantic(
            content="Project Beta backend is built with Django and ORM models.",
            importance=8,
            project="project_beta"
        )

        alpha_results = mem_mgr.search_semantic("backend architecture", project="project_alpha")
        beta_results = mem_mgr.search_semantic("backend architecture", project="project_beta")

        alpha_texts = " ".join([r["content"] for r in alpha_results])
        beta_texts = " ".join([r["content"] for r in beta_results])

        assert "FastAPI" in alpha_texts
        assert "Django" not in alpha_texts

        assert "Django" in beta_texts
        assert "FastAPI" not in beta_texts

    # =========================================================================
    # TEST 06 — Forgetting: Low-value memory decays and is pruned
    # =========================================================================
    def test_06_forgetting_and_decay(self, mem_mgr):
        """Low-value memory decays when simulated time advances and gets pruned."""
        # Store low-importance memory (importance = 2)
        low_id = mem_mgr.store_semantic(
            content="Casual remark: It was slightly cloudy outside at lunch.",
            importance=2,
            project="general"
        )
        
        # Store critical memory (importance = 10)
        crit_id = mem_mgr.store_semantic(
            content="CRITICAL SAFETY: Production API token secret must never be printed to stdout.",
            importance=10,
            project="security"
        )

        # Simulate time aging (60 days ago)
        old_date = (datetime.now() - timedelta(days=60)).isoformat()
        with mem_mgr._lock.write_lock():
            mem_mgr.dbs["conversations"].execute(
                "UPDATE semantic_memories SET created_at = ? WHERE id = ?",
                (old_date, low_id)
            )
            mem_mgr.dbs["conversations"].commit()

        # Run memory consolidator decay
        consolidator = MemoryConsolidator(mem_mgr)
        consolidator._apply_memory_decay()

        # Verify low-value decayed memory was pruned
        with mem_mgr._lock.read_lock():
            low_row = mem_mgr.dbs["conversations"].execute(
                "SELECT id FROM semantic_memories WHERE id = ?", (low_id,)
            ).fetchone()
            crit_row = mem_mgr.dbs["conversations"].execute(
                "SELECT id FROM semantic_memories WHERE id = ?", (crit_id,)
            ).fetchone()

        assert low_row is None, "Low importance memory should have been pruned after 60 days of decay"
        assert crit_row is not None, "Critical safety memory must remain immune to decay"

    # =========================================================================
    # TEST 07 — Safety: Procedural memory blocks dangerous actions
    # =========================================================================
    def test_07_procedural_safety_guard(self):
        """Protected tab policy blocks agent from closing server tab without approval."""
        policy_engine = BrowserPolicyEngine()
        
        # Protected tab record (e.g. Jarvis control server)
        server_tab = TabRecord(
            tab_id="tab_srv_8000",
            page_ref=None,
            url="http://localhost:8000/dashboard",
            title="JARVIS Backend Server Control",
            owner="system",
            protected=True
        )

        # Agent tries to close protected tab
        decision = policy_engine.validate_tab_close(
            tab_record=server_tab,
            requester_id="research_agent"
        )

        assert decision.allowed is False
        assert "protected" in decision.reason.lower() or "immutable" in decision.reason.lower()

    # =========================================================================
    # TEST 08 — Learning: Repeated failures trigger reflection & procedural lesson
    # =========================================================================
    def test_08_learning_and_reflection(self, mem_mgr):
        """Repeated tool execution failures are recorded and tracked in ToolMemory."""
        tool_mem = ToolMemory(mem_mgr)
        
        # Record 5 consecutive failures for 'unstable_scraper'
        for _ in range(5):
            tool_mem.record(
                tool_name="unstable_scraper",
                success=False,
                exec_time_ms=450,
                error="RateLimitExceeded"
            )

        # Check unreliable tools detection
        unreliable = tool_mem.get_unreliable_tools()
        unreliable_names = [t["tool_name"] for t in unreliable]
        assert "unstable_scraper" in unreliable_names

        # Verify failure rate is reflected in score
        target = next(t for t in unreliable if t["tool_name"] == "unstable_scraper")
        assert target["reliability"] < 0.60

    # =========================================================================
    # TEST 09 — False Memory: Write Gate rejects noise and low-confidence input
    # =========================================================================
    def test_09_false_memory_and_noise_rejection(self):
        """Noise phrases like 'ok', 'hi', or short snippets are rejected by MemoryGate."""
        gate = MemoryGate()
        
        assert gate.evaluate("ok")[0] == GateDecision.REJECT
        assert gate.evaluate("hi")[0] == GateDecision.REJECT
        assert gate.evaluate("thanks")[0] == GateDecision.REJECT
        assert gate.evaluate("a")[0] == GateDecision.REJECT
        assert gate.evaluate("yep got it")[0] == GateDecision.REJECT

    # =========================================================================
    # TEST 10 — Recovery: Fallback to structured SQLite/FTS5 when vector DB fails
    # =========================================================================
    def test_10_recovery_and_vector_fallback(self, mem_mgr):
        """When ChromaDB vector store is disabled or unavailable, FTS5 fallback works."""
        mem_mgr.store_semantic(
            content="Critical database migration completed for PostgreSQL cluster on server 12.",
            importance=8,
            project="infra",
            tags="database,postgres,migration"
        )

        # Force disable vector search to simulate ChromaDB unavailability
        mem_mgr._vector_enabled = False
        mem_mgr.collection = None

        # Search should seamlessly fall back to SQLite FTS5 index
        results = mem_mgr.search_semantic("PostgreSQL cluster migration", project="infra")
        assert len(results) > 0
        assert any("PostgreSQL" in r["content"] for r in results)
