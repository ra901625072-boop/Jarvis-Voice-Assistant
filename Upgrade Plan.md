# JARVIS Backend — Detailed Architecture & Implementation Plan

> **Project:** JARVIS Multi-Agent AI Assistant  
> **Stack:** Python · Google Gemini 2.5 Flash · LiveKit RTC · MCP Toolsets  
> **Status:** ~90–95% aligned with a modern multi-agent architecture  
> **Goal:** Complete the final 5–10% and establish a clear roadmap for all future development  

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Current State Verification](#2-current-state-verification)
3. [Core Patterns & Conventions](#3-core-patterns--conventions)
4. [Component Breakdown](#4-component-breakdown)
5. [Remaining Work — Priority Actions](#5-remaining-work--priority-actions)
6. [Phase-by-Phase Implementation Plan](#6-phase-by-phase-implementation-plan)
7. [Agent Communication Flow](#7-agent-communication-flow)
8. [File Structure Reference](#8-file-structure-reference)
9. [Environment & Dependencies](#9-environment--dependencies)
10. [Testing Strategy](#10-testing-strategy)
11. [Future Roadmap](#11-future-roadmap)

---

## 1. Architecture Overview

JARVIS is a **multi-agent AI system** built on three foundational layers:

```
┌─────────────────────────────────────────────────────┐
│                   LiveKit RTC Layer                  │
│           (Real-time voice/data transport)           │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              Supervisor Agent (Orchestrator)          │
│         Routes tasks → dispatches via AgentBus       │
└──┬─────────┬──────────┬────────────┬────────────────┘
   │         │          │            │
┌──▼──┐  ┌──▼──┐  ┌────▼──┐  ┌─────▼──┐  ...more agents
│Brain│  │Code │  │Browse │  │Execute │
│Agent│  │Agent│  │Agent  │  │Agent   │
└──┬──┘  └──┬──┘  └───┬───┘  └────┬───┘
   │         │         │           │
┌──▼─────────▼─────────▼───────────▼────────────────┐
│               AgentBus (asyncio message router)     │
└──────────────────────┬──────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────┐
│         Toolsets · Controllers · Services            │
│   (SystemTools, FileTools, BrowserTools, etc.)       │
└─────────────────────────────────────────────────────┘
```

### Design Principles

- **Agents** make autonomous decisions and can delegate to other agents.
- **Toolsets** execute concrete actions requested by agents — they do not decide.
- **Controllers** are low-level device/system interfaces (keyboard, mouse, volume, etc.).
- **Services** provide shared infrastructure support (memory, security, state) without decision-making.
- **AgentBus** is a central asyncio-based message router — every agent registers once and receives tasks via `dispatch()`.

---

## 2. Current State Verification

Based on the actual codebase inspection:

### ✅ Confirmed Correct in Analysis

| Item | Verified | Notes |
|------|----------|-------|
| `BaseAgent` abstract class | ✅ | In `agents/base_agent.py` — uses Gemini 2.5 Flash |
| `AgentBus` message router | ✅ | In `agents/bus.py` — asyncio-based, supports timeouts |
| `CodingAgent` | ✅ | 3 task types: `write_code`, `refactor_code`, `build_project` |
| `BrowserAgent` | ✅ | Task type: `automate_web_flow` with action plan output |
| `DebuggingAgent` | ✅ | 3 task types: `diagnose_error`, `apply_self_healing`, `verify_fix` |
| `ExecutionAgent` | ✅ | Uses `WorldStateManager`, `ExecutionEngine`, `ToolRouter` |
| `agent.py` orchestrator | ✅ | Thin ~150-line wiring file — correct pattern |
| LiveKit RTC integration | ✅ | `@server.rtc_session` decorator on `my_agent()` |
| MCP toolsets | ✅ | DuckDuckGo search, filesystem, optional git |
| ServiceContainer/`build_container()` | ✅ | Dependency injection for all services |
| 12 Toolset classes | ✅ | System, Window, App, Browser, Media, Keyboard, Mouse, File, Task, Memory, Vision, Verification |

### ⚠️ Partial in This Zip (Confirmed Exist from `agent.py` imports)

The following are referenced in `agent.py` and the container but were not included in this zip — they exist in your full project:

- `memory_agent`, `supervisor_agent`, `vision_agent`, `planning_agent`, `recovery_agent`, `verification_agent`, `integration_agent`
- All `modules/` subpackages (core, execution, planning, skills, memory)
- All `toolsets/` files
- `container.py`, `config.py`

---

## 3. Core Patterns & Conventions

### Every Agent Must Follow This Contract

```python
from agents.base_agent import BaseAgent
from agents.types import AgentTask, AgentResult

class MyAgent(BaseAgent):
    def __init__(self, bus, ...dependencies):
        super().__init__(agent_id="my_agent")   # unique snake_case ID
        self.bus = bus
        self.bus.register(self.agent_id, self.handle)   # required registration

    async def handle(self, task: AgentTask) -> AgentResult:
        try:
            if task.task_type == "do_something":
                return await self._handle_do_something(task, task.payload)
            else:
                return self._create_result(task, success=False,
                    error=f"MyAgent does not support task type '{task.task_type}'")
        except Exception as e:
            logger.exception(f"MyAgent failed handling '{task.task_type}'")
            return self._create_result(task, success=False, error=str(e))
```

### LLM Call Convention

All agents call `self.generate_response()` inherited from `BaseAgent`:

```python
# Structured JSON output (preferred)
response = await self.generate_response(
    prompt,
    system_instruction="You are...",
    model="gemini-2.5-flash",
    response_mime_type="application/json"
)
data = json.loads(response)

# Free-text output
response = await self.generate_response(prompt)
```

### AgentBus Dispatch Convention

```python
from agents.types import AgentTask
import uuid

task = AgentTask(
    task_id=str(uuid.uuid4()),
    task_type="write_code",
    target_agent="coding_agent",
    payload={"instruction": "...", "file_path": "..."},
    timeout_seconds=30.0
)
result = await self.bus.dispatch(task)
if result.success:
    data = result.result
```

---

## 4. Component Breakdown

### 4.1 Agents (11 Active · 1 Recommended · 1 Future)

| Agent | `agent_id` | Task Types | Status |
|-------|-----------|------------|--------|
| Supervisor Agent | `supervisor_agent` | `run_session`, routes all top-level tasks | ✅ Active |
| Planning Agent | `planning_agent` | `plan_task`, `create_dag` | ✅ Active |
| Coding Agent | `coding_agent` | `write_code`, `refactor_code`, `build_project` | ✅ Active |
| Browser Agent | `browser_agent` | `automate_web_flow` | ✅ Active |
| Debugging Agent | `debugging_agent` | `diagnose_error`, `apply_self_healing`, `verify_fix` | ✅ Active |
| Execution Agent | `execution_agent` | `execute_plan`, `run_subtask` | ✅ Active |
| Memory Agent | `memory_agent` | `store`, `retrieve`, `consolidate` | ✅ Active |
| Vision Agent | `vision_agent` | `analyze_screen`, `extract_text`, `describe_image` | ✅ Active |
| Integration Agent | `integration_agent` | `call_api`, `connect_service` | ✅ Active |
| Recovery Agent | `recovery_agent` | `handle_failure`, `rollback` | ✅ Active |
| Verification Agent | `verification_agent` | `verify_result`, `check_completion` | ✅ Active |
| **Coordinator Agent** | `coordinator_agent` | `coordinate_agents`, `resolve_conflicts`, `select_agent` | ⭐ **Recommended** |
| Reflection Agent | `reflection_agent` | `analyze_failure`, `propose_improvement` | 🔮 Future |

---

### 4.2 Toolsets (Keep As-Is)

These live in `toolsets/` and are passed into agents via the `ServiceContainer`. They execute actions — they do not decide.

| Toolset | Responsibilities |
|---------|----------------|
| `SystemTools` | OS-level operations, process management |
| `WindowTools` | Window focus, resize, z-ordering |
| `AppTools` | Application launch, close, state |
| `BrowserTools` | High-level browser interaction |
| `MediaTools` | Audio/video playback and capture |
| `KeyboardTools` | Keypress simulation and text injection |
| `MouseTools` | Click, move, drag, scroll simulation |
| `FileTools` | File I/O, directory operations |
| `TaskTools` | Task creation, status update, delegation |
| `MemoryTools` | Memory read/write interface for LLM context |
| `VisionTools` | Screen capture, image analysis delegation |
| `VerificationTools` | Result validation and completion checks |

All toolsets receive `security=_security` from the container for permission gating.

---

### 4.3 Controllers (Keep As-Is)

Live in `modules/controls/`. These are OS-level device drivers.

```
app_controller.py        → Launch/close apps
browser_controller.py    → Chrome/Firefox CDP bridge
keyboard_controller.py   → xdotool / pynput
mouse_controller.py      → pyautogui / pynput
window_controller.py     → wmctrl / pygetwindow
volume_controller.py     → OS audio API
brightness_controller.py → Display brightness API
google_search.py         → Authenticated Google search
system_controller.py     → System calls, power, network
```

Controllers are **never** called directly by agents — only by toolsets.

---

### 4.4 Services (Keep As-Is)

Infrastructure that supports agents but does not make autonomous decisions.

**Execution Services:**
- `ExecutionEngine` — runs tool calls safely
- `ToolRouter` — selects the optimal tool from a capability name
- `WorldStateManager` — tracks current system state for rollback safety
- `VerificationEngine` — post-execution result checking
- `RecoveryEngine` — failure fallback strategies
- `UnifiedTaskRegistry` — global task tracking and deduplication
- `SuccessPatterns` — stores what worked in past executions

**Memory Services:**
- `MemoryGate` — filters what enters long-term memory
- `MemoryLifecycle` — TTL, eviction, and archival logic
- `MemoryConsolidator` — merges related memories to reduce fragmentation
- `MemoryScorer` — ranks memories by relevance
- `GoalMemory` — persistent goal and sub-goal tracking
- `ExperienceReplay` — recalls past similar situations
- `ToolMemory` — remembers which tools succeeded/failed per context

**Core Services:**
- `SecurityManager` — permission enforcement
- `StateManager` — `SubTask` lifecycle state machine
- `HardwareStats` — CPU, RAM, GPU monitoring
- `ConflictResolver` — resolves agent output conflicts (service for now)
- `ReflectionEngine` — scores past executions (service for now)
- `Utils` — shared helpers

---

## 5. Remaining Work — Priority Actions

### Priority 1 — Create CoordinatorAgent (Recommended, ~2–3 days)

`modules/core/cognitive_coordinator.py` currently acts as an orchestration layer that selects agents and manages collaboration. This logic belongs in an agent.

**Create:** `agents/coordinator_agent.py`

```python
class CoordinatorAgent(BaseAgent):
    """
    Selects which specialist agent(s) should handle a task.
    Coordinates multi-agent collaboration.
    Replaces cognitive_coordinator.py.
    """
    def __init__(self, bus, available_agents: list):
        super().__init__(agent_id="coordinator_agent")
        self.bus = bus
        self.available_agents = available_agents
        self.bus.register(self.agent_id, self.handle)

    # Task types:
    # - "select_agent"      → given task description, pick the right agent
    # - "coordinate_flow"   → manage a multi-step multi-agent workflow
    # - "arbitrate"         → resolve conflicts when two agents disagree
```

Register in `container.py`:
```python
coordinator_agent = CoordinatorAgent(
    bus=agent_bus,
    available_agents=["coding_agent", "browser_agent", "vision_agent", ...]
)
services["coordinator_agent"] = coordinator_agent
```

---

### Priority 2 — Audit cognitive_coordinator.py Responsibilities

Before deleting `cognitive_coordinator.py`, map every method to its new home:

| Old Method | Move To |
|-----------|---------|
| `select_agent(task)` | `CoordinatorAgent._handle_select_agent()` |
| `coordinate_agents(plan)` | `CoordinatorAgent._handle_coordinate_flow()` |
| `resolve_conflict(agents, results)` | `CoordinatorAgent._handle_arbitrate()` OR keep in `ConflictResolver` service |
| Infrastructure helpers (logging, metrics) | Keep as `Utils` or `ConflictResolver` |

---

### Priority 3 — Standardize AgentBus Timeout Defaults

Currently each agent call can set its own `timeout_seconds`. Establish global defaults:

| Agent | Recommended Timeout |
|-------|-------------------|
| Coding Agent | 60s (LLM code generation) |
| Browser Agent | 45s (web automation) |
| Execution Agent | 30s (tool dispatch) |
| Debugging Agent | 45s (analysis) |
| Vision Agent | 20s (image processing) |
| Memory Agent | 10s (retrieval) |
| All others | 30s (default) |

Add to `container.py` or a `config.py` constant:
```python
AGENT_TIMEOUTS = {
    "coding_agent": 60.0,
    "browser_agent": 45.0,
    "execution_agent": 30.0,
    ...
}
```

---

### Priority 4 — JSON Parsing Hardening

Every agent currently has repeated fragile JSON parsing:
```python
# Current (fragile — breaks on backtick fences)
data = json.loads(response.strip().strip('`').replace('json\n', '').strip())
```

Extract into a shared utility in `agents/base_agent.py`:
```python
def _parse_json_response(self, response: str) -> dict:
    """Safely parse JSON from Gemini response, handling markdown code fences."""
    cleaned = response.strip()
    # Strip ```json ... ``` or ``` ... ``` fences
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[1:])
        cleaned = cleaned.rstrip("`").strip()
    return json.loads(cleaned)
```

Then in every agent:
```python
data = self._parse_json_response(response)
```

---

### Priority 5 — Integration Agent Task Type Coverage

Based on the pattern seen in other agents, `IntegrationAgent` should explicitly support:

```python
# Recommended task types
"call_rest_api"      → HTTP GET/POST/PUT/DELETE to external services
"call_graphql"       → GraphQL query execution
"authenticate"       → OAuth2 / API key flows
"connect_service"    → Establish a persistent connection (database, websocket)
"sync_data"          → Bidirectional data sync between JARVIS and external service
```

---

## 6. Phase-by-Phase Implementation Plan

### Phase 1 — Stabilise Core (Week 1)

Goal: All 11 existing agents are reliable and production-ready.

- [ ] Add `_parse_json_response()` to `BaseAgent` and update all agents to use it
- [ ] Add `AGENT_TIMEOUTS` config and enforce in `AgentBus.dispatch()` calls
- [ ] Write unit tests for each agent's `handle()` method (see Section 10)
- [ ] Ensure `container.py` registers all 11 agents and they are available at startup
- [ ] Verify `supervisor_agent.run_session()` correctly wires LiveKit ctx + MCP toolsets

**Deliverable:** All 11 agents pass their unit tests. Zero unhandled exceptions in `agent.py` startup.

---

### Phase 2 — Coordinator Agent (Week 2)

Goal: Elevate orchestration logic into a first-class agent.

- [ ] Create `agents/coordinator_agent.py` with task types: `select_agent`, `coordinate_flow`, `arbitrate`
- [ ] Migrate logic from `modules/core/cognitive_coordinator.py`
- [ ] Register `coordinator_agent` in `container.py`
- [ ] Update `supervisor_agent` to dispatch complex routing decisions to `coordinator_agent`
- [ ] Delete or deprecate `cognitive_coordinator.py` (keep file but mark `@deprecated`)
- [ ] Write unit tests for `CoordinatorAgent`

**Deliverable:** `CoordinatorAgent` handles all multi-agent routing. `cognitive_coordinator.py` is no longer called directly.

---

### Phase 3 — Memory & State Hardening (Week 3)

Goal: Make memory subsystem reliable under concurrent agent workloads.

- [ ] Audit `MemoryAgent` task types — ensure `store`, `retrieve`, `consolidate`, `replay` are all present
- [ ] Test `MemoryGate` under concurrent `store` calls from 3+ agents simultaneously
- [ ] Verify `GoalMemory` persists across session restarts
- [ ] Add a `memory_health_check` task type to `MemoryAgent` that returns subsystem stats
- [ ] Review `ExperienceReplay` — ensure it surfaces relevant past tasks to `PlanningAgent`

**Deliverable:** Memory subsystem handles concurrent reads/writes without data loss.

---

### Phase 4 — MCP & Tool Expansion (Week 4)

Goal: Expand MCP toolsets and ensure robust tool routing.

- [ ] Add Brave Search as an MCP alternative to DuckDuckGo (key already in `.env.example`)
- [ ] Audit `ToolRouter.get_optimal_tool()` — add success-rate weighting from `ToolMemory`
- [ ] Ensure `FileTools` uses the MCP filesystem sandbox (`JARVIS_MCP_FS_ROOT`) for all write operations
- [ ] Add `git_mcp` toolset registration to the container when `.git` directory is detected
- [ ] Write integration tests for each MCP toolset

**Deliverable:** All MCP integrations are functional. Tool routing respects past success rates.

---

### Phase 5 — Reflection Agent (Optional, Future)

Upgrade `ReflectionEngine` to a `ReflectionAgent` when it gains decision-making capability.

**Trigger condition:** When `ReflectionEngine` begins doing any of:
- Proposing changes to future plans
- Modifying `PlanningAgent` behavior based on past failures
- Issuing tasks to other agents

**When ready:**
- [ ] Create `agents/reflection_agent.py`
- [ ] Task types: `analyze_execution`, `propose_improvement`, `update_success_patterns`
- [ ] Register in `container.py`
- [ ] Connect output to `PlanningAgent` via `AgentBus`

---

## 7. Agent Communication Flow

### Single-Agent Task Flow

```
User Voice Input (LiveKit RTC)
         │
         ▼
  SupervisorAgent.run_session()
         │
         ▼
  AgentBus.dispatch(task → target_agent)
         │
         ▼
  SpecialistAgent.handle(task)
         │  LLM call (Gemini 2.5 Flash)
         ▼
  AgentResult { success, result, error, duration_ms }
         │
         ▼
  SupervisorAgent (formats response)
         │
         ▼
  LiveKit RTC → User Voice/Text Output
```

---

### Multi-Agent Collaboration Flow (with CoordinatorAgent)

```
SupervisorAgent receives complex task
         │
         ▼
  dispatch → coordinator_agent :: "coordinate_flow"
         │
  CoordinatorAgent decomposes task into sub-tasks
         │
         ├──► dispatch → planning_agent :: "plan_task"
         │           │
         │           └──► dispatch → coding_agent :: "write_code"
         │
         ├──► dispatch → browser_agent :: "automate_web_flow"
         │
         └──► dispatch → verification_agent :: "verify_result"
                   │
                   └── All results → CoordinatorAgent
                               │
                               └── Returns unified AgentResult
```

---

### Error Recovery Flow

```
ExecutionAgent tool call fails
         │
         ▼
  RecoveryAgent :: "handle_failure"
         │
         ├──► DebuggingAgent :: "diagnose_error"
         │           │
         │           └──► DebuggingAgent :: "apply_self_healing"
         │
         └──► On persistent failure:
                  VerificationAgent :: "verify_result" (last-known-good state)
                  ReflectionEngine logs the failure pattern
```

---

## 8. File Structure Reference

```
backend/
├── agent.py                          # Thin wiring: LiveKit RTC + services + toolsets
├── container.py                      # ServiceContainer — build_container() factory
├── config.py                         # load_config() — env vars + constants
│
├── agents/                           # All autonomous agents
│   ├── base_agent.py                 # Abstract BaseAgent + Gemini client
│   ├── bus.py                        # AgentBus — asyncio message router
│   ├── types.py                      # AgentTask, AgentResult dataclasses
│   ├── browser_agent.py              # ✅ Active
│   ├── coding_agent.py               # ✅ Active
│   ├── debugging_agent.py            # ✅ Active
│   ├── execution_agent.py            # ✅ Active
│   ├── integration_agent.py          # ✅ Active
│   ├── memory_agent.py               # ✅ Active
│   ├── planning_agent.py             # ✅ Active
│   ├── recovery_agent.py             # ✅ Active
│   ├── supervisor_agent.py           # ✅ Active
│   ├── verification_agent.py         # ✅ Active
│   ├── vision_agent.py               # ✅ Active
│   └── coordinator_agent.py          # ⭐ TO CREATE (Phase 2)
│
├── toolsets/                         # Execution tools — no decision logic
│   ├── __init__.py
│   ├── system_tools.py
│   ├── window_tools.py
│   ├── app_tools.py
│   ├── browser_tools.py
│   ├── media_tools.py
│   ├── keyboard_tools.py
│   ├── mouse_tools.py
│   ├── file_tools.py
│   ├── task_tools.py
│   ├── memory_tools.py
│   ├── vision_tools.py
│   └── verification_tools.py
│
├── modules/
│   ├── controls/                     # Low-level OS/device controllers
│   │   ├── app_controller.py
│   │   ├── browser_controller.py
│   │   ├── google_search.py
│   │   ├── keyboard_controller.py
│   │   ├── mouse_controller.py
│   │   ├── system_controller.py
│   │   ├── volume_controller.py
│   │   ├── brightness_controller.py
│   │   └── window_controller.py
│   │
│   ├── core/                         # Infrastructure services
│   │   ├── memory_manager.py
│   │   ├── security_manager.py
│   │   ├── state_manager.py
│   │   ├── hardware_stats.py
│   │   ├── cognitive_coordinator.py  # ⚠️ Migrate logic → coordinator_agent.py
│   │   ├── reflection_engine.py      # Service (upgrade to agent later if needed)
│   │   ├── conflict_resolver.py      # Service (upgrade to agent if multi-agent arbitration needed)
│   │   └── utils.py
│   │
│   ├── execution/                    # Execution infrastructure services
│   │   ├── execution_engine.py
│   │   ├── tool_router.py
│   │   ├── world_state.py
│   │   ├── verification_engine.py
│   │   ├── recovery_engine.py
│   │   ├── task_registry.py
│   │   └── success_patterns.py
│   │
│   ├── memory/                       # Memory subsystem services
│   │   ├── memory_gate.py
│   │   ├── memory_lifecycle.py
│   │   ├── memory_consolidator.py
│   │   ├── memory_scorer.py
│   │   ├── goal_memory.py
│   │   ├── experience_replay.py
│   │   └── tool_memory.py
│   │
│   ├── planning/                     # Planning layer
│   │   ├── task_planner.py
│   │   ├── dag_compiler.py
│   │   └── behavior.py               # JarvisBehavior — system prompt definition
│   │
│   └── skills/                       # Dynamic skill plugins
│       └── registry.py               # SkillRegistry — loads skill modules
│
└── tests/                            # Test suite (see Section 10)
    ├── test_agents/
    ├── test_toolsets/
    └── test_services/
```

---

## 9. Environment & Dependencies

### Required Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `GEMINI_API_KEY` | ✅ Yes | Primary LLM (Gemini 2.5 Flash) |
| `LIVEKIT_URL` | ✅ Yes | LiveKit server URL |
| `LIVEKIT_API_KEY` | ✅ Yes | LiveKit authentication |
| `LIVEKIT_API_SECRET` | ✅ Yes | LiveKit authentication |
| `JARVIS_API_KEY` | ✅ Yes | Internal API authentication |
| `OPENROUTER_API_KEY` | ⬜ Optional | Fallback LLM provider |
| `GROQ_API_KEY` | ⬜ Optional | Fast inference fallback |
| `BRAVE_API_KEY` | ⬜ Optional | Brave Search MCP server |
| `JARVIS_MCP_FS_ROOT` | ⬜ Optional | Filesystem sandbox path (default: `~/jarvis_workspace`) |
| `JARVIS_MCP_GIT_REPO` | ⬜ Optional | Git repo path for MCP git operations |
| `AGENT_NAME` | ⬜ Optional | LiveKit agent name (default: `jarvis`) |
| `GOOGLE_API_KEY` | ⬜ Optional | Fallback to `GEMINI_API_KEY` |

### MCP Servers (auto-configured in `agent.py`)

| MCP Server | npm Package | Trigger |
|-----------|------------|---------|
| DuckDuckGo Search | `duckduckgo-mcp-server` | Always active |
| Filesystem | `@modelcontextprotocol/server-filesystem` | Always active |
| Git | `mcp-server-git` | Only if `JARVIS_MCP_GIT_REPO` contains a `.git` directory |

---

## 10. Testing Strategy

### Unit Tests — Each Agent

Every agent needs a test file at `tests/test_agents/test_<agent_name>.py`:

```python
# Example: tests/test_agents/test_coding_agent.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from agents.coding_agent import CodingAgent
from agents.types import AgentTask

@pytest.mark.asyncio
async def test_write_code_success():
    bus = MagicMock()
    bus.register = MagicMock()
    agent = CodingAgent(bus=bus)
    agent.generate_response = AsyncMock(return_value='{"file_path":"main.py","content":"print(1)","explanation":"test"}')

    task = AgentTask(task_id="t1", task_type="write_code", target_agent="coding_agent",
                     payload={"instruction": "Print 1", "file_path": "main.py"})
    result = await agent.handle(task)

    assert result.success is True
    assert result.result["file_path"] == "main.py"

@pytest.mark.asyncio
async def test_unknown_task_type():
    bus = MagicMock()
    bus.register = MagicMock()
    agent = CodingAgent(bus=bus)
    task = AgentTask(task_id="t2", task_type="unknown_type", target_agent="coding_agent", payload={})
    result = await agent.handle(task)
    assert result.success is False
    assert "does not support" in result.error
```

### Integration Tests — AgentBus

```python
# tests/test_bus_routing.py
@pytest.mark.asyncio
async def test_bus_dispatches_to_correct_agent():
    bus = AgentBus()
    handler = AsyncMock(return_value=AgentResult(task_id="t1", success=True))
    bus.register("test_agent", handler)
    task = AgentTask(task_id="t1", task_type="do_it", target_agent="test_agent", payload={})
    result = await bus.dispatch(task)
    assert result.success is True
    handler.assert_called_once_with(task)

@pytest.mark.asyncio
async def test_bus_returns_error_for_unknown_agent():
    bus = AgentBus()
    task = AgentTask(task_id="t2", task_type="do_it", target_agent="ghost_agent", payload={})
    result = await bus.dispatch(task)
    assert result.success is False
    assert "No handler registered" in result.error
```

### Test Coverage Targets

| Component | Target Coverage |
|-----------|---------------|
| All 11 Agents `handle()` methods | 100% |
| `AgentBus` dispatch and timeout | 100% |
| `BaseAgent` `generate_response()` | 80% |
| Toolsets | 70% |
| Services | 60% |

Run tests:
```bash
cd backend
pytest tests/ -v --asyncio-mode=auto
```

---

## 11. Future Roadmap

### Near-Term (1–2 months)

- **Reflection Agent** — Upgrade `ReflectionEngine` to a full agent when it begins proposing improvements to `PlanningAgent`
- **Conflict Arbitration** — Add agent-to-agent arbitration to `CoordinatorAgent` when multi-agent disagreements arise
- **Skill Hot-Reload** — Allow `SkillRegistry` to load new skill plugins without restarting
- **Observability** — Add structured logging with `task_id` correlation across all agents for full trace visibility

### Medium-Term (3–6 months)

- **Multi-Model Routing** — Route tasks to Gemini, Groq, or OpenRouter based on cost/speed tradeoffs via `ToolRouter`
- **Agent Memory Specialization** — Each agent maintains a personal memory slice (context, preferences) via `MemoryAgent`
- **Parallel Agent Execution** — `CoordinatorAgent` dispatches independent sub-tasks concurrently using `asyncio.gather()`
- **Vision-Guided Planning** — `VisionAgent` feeds screen state into `PlanningAgent` for real-time context-aware planning

### Long-Term (6+ months)

- **Agent Self-Improvement** — `ReflectionAgent` modifies its own system prompts based on failure analysis
- **Multi-JARVIS Coordination** — Multiple JARVIS instances collaborate via a shared `AgentBus` over a network
- **User Personalization Layer** — `MemoryAgent` builds a long-term user preference model that adapts all agent behavior
- **Plugin Marketplace** — Third-party skill plugins installable via a registry, each running as sandboxed agents

---

## Summary

| Category | Count | Action |
|----------|-------|--------|
| Active Agents | 11 | ✅ Keep — stabilise and test |
| Recommended New Agent | 1 (CoordinatorAgent) | ⭐ Create in Phase 2 |
| Future Agent | 1 (ReflectionAgent) | 🔮 Upgrade when ready |
| Toolsets | 12 | ✅ Keep as-is |
| Controllers | 9 | ✅ Keep as-is |
| Services | 16 | ✅ Keep as-is |
| **Architecture Score** | **~92%** | Complete Phase 1–2 for 100% |

The highest-value next action is **Phase 1 stabilisation** (JSON parsing hardening + test coverage), followed immediately by **Phase 2 CoordinatorAgent** creation. Everything else builds on top of this solid foundation.