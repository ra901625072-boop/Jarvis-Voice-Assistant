# Jarvis → Multi-Automation Swarm: Implementation Plan

**Based on:** analysis of `start_jarvis.zip` (243 Python files, `apps/backend` monolith with 15+ agents under `ai/agents/`, `modules/bus/{base_bus,redis_bus}.py`, `events/bus.py` (`AgentBus`), `modules/execution/world_state.py`, `container.py` (`ServiceContainer`)).

**Confirmed in code:**
- `RedisBus.dispatch()` in `modules/bus/redis_bus.py` returns `AgentResult(success=False, error="RedisBus dispatch not implemented")` — it is a stub. Only `register()` stores a handler locally; there is no Redis Stream/consumer-group logic, despite the `# Future:` comments already describing the intended design.
- The only working bus is `events/bus.py::AgentBus`, a pure in-process `asyncio` router keyed by `target_agent` in a dict — no persistence, no cross-process delivery, no ack/retry/DLQ.
- `WorldStateManager` (`modules/execution/world_state.py`) is a classic thread-safe singleton (`__new__` + class-level lock) holding `_shared_state` as a plain dict — any agent can read/write any key with no schema or ownership.
- `ServiceContainer` (`container.py`) is imported directly by agents, skills, tools, and even the bus itself (`events/bus.py` imports `from container import ServiceContainer` inside `dispatch()`), so almost every module is coupled to one global object graph.
- `CoordinatorAgent._classify_subtask_mode()` routes purely on string heuristics (prefix lists like `"open "`, `"run "`; keyword lists like `"biggest"`, `"how many"`) with an LLM fallback only when heuristics are `"unsure"` — there is no capability registry, load, or historical-success signal in the routing decision itself (though `SuccessLearner` exists and is *not* consulted here).
- `AgentTask`/`AgentResult` (`ai/agents/types.py`) are plain dataclasses with no schema versioning, no idempotency key, and no explicit success-criteria field.

This plan turns those specific findings into a phased, file-level engineering plan.

**Revision note:** this version incorporates review feedback on the first draft — the bus pattern is now pinned to one exact design (streams both directions, no pub/sub ambiguity), a security/authorization boundary is added (new Phase 1.5), a failure-mode matrix is now a required artifact rather than implied, the verifier's authority is bounded explicitly, and each phase gets rollout/rollback rules plus a named test-layer breakdown instead of a single "exit criteria" line.

---

## Guiding architecture

```
                 ┌─────────────────────────────────────────────┐
                 │              Message Bus (durable)            │
                 │  Redis Streams: jarvis:tasks:{agent}          │
                 │  consumer groups, XACK, XCLAIM, DLQ stream    │
                 └───────────────┬───────────────────────────────┘
                                 │  TaskEnvelope (versioned, signed contract)
       ┌─────────────────────────┼─────────────────────────────────┐
       ▼                         ▼                                 ▼
┌─────────────┐         ┌─────────────────┐                ┌───────────────┐
│  Planner     │  plan   │   Coordinator/   │   route        │  Specialists   │
│  Agent       │────────▶│   Router         │──────────────▶│  (one job each)│
└─────────────┘  graph   │  (capability-    │  by capability │ researcher     │
                         │   based)         │  + load + score │ coder          │
                         └───────┬──────────┘                │ browser-op     │
                                 │                             │ verifier       │
                                 ▼                             │ memory-curator │
                         ┌───────────────┐                    │ recovery       │
                         │ Verifier Agent │◀───────────────────┘───────────────┘
                         └───────┬───────┘
                                 ▼
                         ┌───────────────┐
                         │ Recovery Agent │──▶ re-plan / retry / fallback agent
                         └───────────────┘
```

State is split four ways (Phase 3) instead of one shared `WorldStateManager` singleton, and every agent talks to every other agent **only** through envelopes on the bus (Phase 2) — never through shared Python objects.

---

## Phase 0 — Contracts first (foundation for everything else)

Everything downstream (bus, routing, recovery) depends on the task/message shape being locked down first, so this phase has no code dependencies on the others and should land first.

**Files touched:** `ai/agents/types.py` → split into `ai/contracts/` package.

1. Add `schema_version: str = "1.0"` to both `AgentTask` and `AgentResult`.
2. Add `correlation_id: str` (ties every message in one goal-execution together, distinct from `task_id` which is per-message) and `idempotency_key: str` (hash of `task_type + payload + correlation_id`) to `AgentTask`.
3. Add `success_criteria: Dict[str, Any]` to `AgentTask` — a small declarative contract (e.g. `{"type": "schema_match", "schema": {...}}` or `{"type": "verifier_agent", "checks": [...]}`) so the Verifier (Phase 4) has something concrete to check against instead of guessing.
4. Introduce a `MessageKind` enum and wrap all inter-agent traffic in one envelope type instead of ad-hoc dicts:
   ```python
   class MessageKind(str, Enum):
       TASK_REQUEST = "task_request"
       PROGRESS_UPDATE = "progress_update"
       PARTIAL_RESULT = "partial_result"
       VERIFICATION_REPORT = "verification_report"
       FAILURE_REPORT = "failure_report"
       HANDOFF = "handoff_packet"

   @dataclass
   class Envelope:
       kind: MessageKind
       schema_version: str
       correlation_id: str
       payload: AgentTask | AgentResult | ProgressUpdate | VerificationReport | HandoffPacket
   ```
   This is item 12 from the review (shared collaboration protocol) — implementing it here means the bus (Phase 2) can be written against one wire format from day one instead of retrofitted later.
5. Validate every incoming `Envelope` with `pydantic` (or `dataclasses` + `jsonschema`) at the bus boundary — reject and dead-letter anything that doesn't parse, rather than letting a malformed payload reach agent code (this directly fixes review item 5, "stricter schema validation").
6. Idempotency enforcement: the bus (Phase 2) keeps a short-TTL set of seen `idempotency_key`s in Redis; a duplicate delivery (from an ack timeout + redelivery) short-circuits to the cached prior result instead of re-executing a side-effecting task (e.g. `write_code`, `call_api`).

**Exit criteria:** `ai/contracts/` has 100% test coverage on serialization round-trips and rejection of malformed envelopes; `types.py` becomes a thin re-export for backward compatibility during migration.

---

## Phase 1 — Kill the placeholders (unblock everything else)

Review items 1 and 11. Two concrete stubs exist today and both must become real before anything built on top of them (routing, recovery, observability-driven decisions) can be trusted.

1. **`modules/bus/redis_bus.py`** — replace the stub body with one exact, durable design (no pub/sub anywhere — pub/sub drops messages with no subscriber connected, which defeats the point of durability; everything is a stream, both directions):
   - **Task delivery:** `register(agent_id, handler)` starts a background consumer task per agent: `XGROUP CREATE jarvis:tasks:{agent_id} {agent_id}-group $ MKSTREAM`, then a loop of `XREADGROUP` → invoke handler → `XACK` on success.
   - **Result delivery (also a stream, not pub/sub):** the consumer writes its `AgentResult` to `jarvis:results:{correlation_id}` via `XADD` (using `correlation_id`, not `task_id`, as the stream key — a goal execution can have many tasks, and the caller side needs one place to read all results for that goal back, including for `dispatch_many`). `dispatch(task, timeout)` does `XADD jarvis:tasks:{target_agent} * envelope=<json>` then does a blocking `XREAD BLOCK {timeout_ms} STREAMS jarvis:results:{correlation_id} $` for the matching `task_id`. Because it's a stream, a slow/crashed caller can reconnect and replay from its last-read ID instead of losing the result — this is the concrete fix for the ambiguity in the first draft.
   - Every stream (`jarvis:tasks:*`, `jarvis:results:*`, `jarvis:dlq`) gets a `MAXLEN ~` cap and a TTL-based trim job so Redis memory doesn't grow unbounded; results streams are trimmed only after the caller's `XACK`-equivalent (a `read-cursor` key per correlation_id) confirms consumption.
   - Unacked messages older than a visibility window get reclaimed via `XCLAIM` and redelivered up to `max_retries`; beyond that they're moved to `jarvis:dlq` with the failure reason attached (review item 1: dead-letter handling).
   - `dispatch_many` becomes a real fan-out: publish all tasks under one shared `correlation_id`, then a single `XREAD` loop on `jarvis:results:{correlation_id}` collects all expected `task_id`s until all arrive or the timeout elapses (reuses `AbstractBus.dispatch_many`'s concurrent-gather shape from `base_bus.py`, but backed by one stream read instead of N separate waits).
2. Grep the codebase for other `not implemented` / `NotImplementedError` / `# Future:` / `pass  # TODO` markers (found so far only in `redis_bus.py`, but re-scan `modules/` and `tools/` since the review flagged "some support modules" generically) and either implement or explicitly gate them behind a feature flag with a startup-time assertion so they can never be silently reached in production (`ENABLE_EXPERIMENTAL=false` raises instead of degrading silently).
3. Add a `bus_backend` config switch (`config/settings.py`) so `AgentBus` (in-process) remains available for unit tests / single-process dev mode, and `RedisBus` is used for anything multi-process — both implement the same `AbstractBus` interface so callers never branch on backend.

**Exit criteria:** existing `tests/agents/test_bus_concurrency.py` and `test_bus_routing.py` pass unmodified against `RedisBus` in a docker-compose Redis instance, plus new tests for ack/retry/DLQ/idempotency.

---

## Phase 2 — Durable bus as the only communication path

Review item 1 + item 6 (concurrency). Builds on Phase 1's working `RedisBus`.

1. **Per-agent concurrency limits:** each consumer loop wraps handler invocation in `asyncio.Semaphore(agent_concurrency_limit)`, configured per agent type in `config/settings.py` (e.g. `browser_agent: 2`, `coder_agent: 4`) — a browser-driving agent shouldn't run 20 concurrent tabs just because the queue has 20 items.
2. **Tool-level rate limiting:** wrap tool invocation (`tools/builtin/*`) with a token-bucket limiter keyed by tool name, so e.g. two agents calling the same external API don't jointly exceed its rate limit — this has to live at the tool layer, not the agent layer, since multiple agent types can call the same tool.
3. **Cancellation propagation:** add `cancel(correlation_id)` to `AbstractBus` — publishes a `HANDOFF`-adjacent `CANCEL` control message on every agent's stream; each consumer checks a `cancelled_correlation_ids` set before starting work on a message and drops it (with a `FAILURE_REPORT: cancelled`) if the goal was aborted upstream (e.g. the user cancelled, or the Verifier already got a good-enough answer from a parallel branch).
4. **Backpressure:** track queue depth per agent (`XLEN`); when depth exceeds a configured watermark, `dispatch()` on that agent's stream either blocks the caller with exponential backoff or returns a typed `AgentResult(error="backpressure", metadata={"retry_after": n})` that the Coordinator (Phase 4) can react to by picking a different capable agent or delaying re-dispatch.
5. Delete direct handler-dict access patterns; `AgentBus`/`RedisBus` become the *only* legal way one agent's code ever references another agent — no agent module is allowed to `import` another agent's class directly (enforce with an import-linter rule in CI, since today nothing stops e.g. `coordinator/agent.py` from reaching into `interaction_agent` internals).

**Exit criteria:** load test with 200 concurrent tasks across 5 agent types shows correct concurrency caps, no lost messages on a killed consumer process, and DLQ populated for injected failures.

---

## Phase 3 — Split state (kill the global singletons)

Review items 2 and 6. Targets `modules/execution/world_state.py` (`WorldStateManager`) and `container.py` (`ServiceContainer`), which today are imported and mutated from agents, skills, tools, and even the bus's own `dispatch()`.

Replace the one singleton with four explicit, narrowly-scoped stores:

| Store | Lifetime | Example content | Replaces |
|---|---|---|---|
| `SessionState` | one user session / conversation | active window, clipboard, UI focus | parts of `WorldStateManager._shared_state` |
| `GoalState` | one goal execution (one `correlation_id`) | plan graph, per-node status, partial results | ad-hoc dicts passed around `CoordinatorAgent` |
| `LongTermMemory` | persistent across sessions | episodic memory, success patterns, tool reliability stats | existing `memory_manager` / `SuccessLearner` — keep these, but access only via message contracts, not direct method calls from agents that aren't the Memory Curator |
| `ExecutionContext` | one task attempt (retried attempts get a fresh one) | timeout budget, retry count, trace span | implicit today, scattered across `dispatch()` locals in `events/bus.py` |

1. Each store gets its own accessor class with an explicit read/write API (no generic `get_shared_state(key)`/`set_shared_state(key, value)` string-keyed bag — replace `WorldStateManager`'s stringly-typed dict with typed fields per concern).
2. `WorldStateManager`'s actual OS-level responsibilities (running processes, open windows, clipboard — the `psutil`/`pygetwindow`/`pyperclip` calls) are legitimate and stay, but get renamed/scoped as `SystemSnapshotProvider` and treated as a **read-only sensor**, not a place to stash arbitrary shared mutable state (`update_shared_state`/`get_shared_state` are removed).
3. `ServiceContainer` stops being imported ad hoc through the codebase (currently in ~30 files including `events/bus.py`, every agent's `agent.py`, `api/dependencies.py`, skills, tools). Instead: only composition-root code (`apps/backend/agent.py`, `api/dependencies.py`) builds the container and injects specific dependencies into agent constructors — agents declare what they need (`memory_manager`, `bus`) as constructor args, which `CoordinatorAgent` already does, so this is largely tightening an existing good pattern rather than inventing a new one.
4. Any inter-agent data flow that today goes through `WorldStateManager` gets converted to a `PARTIAL_RESULT` or `HANDOFF` envelope on the bus instead — e.g. if `InteractionAgent` currently reads a value the `CoordinatorAgent` stashed in shared state, that value now travels as `payload` on the dispatched `AgentTask`.

**Exit criteria:** `grep -r "WorldStateManager()" apps/backend` returns only the `SystemSnapshotProvider` internals; `grep -r "from container import ServiceContainer"` returns only the composition root and DI wiring, not agent/skill/tool modules.

---

## Phase 4 — Planner → Executor → Verifier → Recovery loop

Review items 3, 4, 8, 9. This is the behavioral core, built on Phases 0–3.

### 4a. Capability-based routing (replaces `CoordinatorAgent._classify_subtask_mode`)

Add a `CapabilityRegistry`:
```python
@dataclass
class AgentCapability:
    agent_id: str
    task_types: set[str]          # what it can do at all
    confidence_by_task_type: dict[str, float]   # rolling average from AgentResult.confidence
    current_load: int             # from bus queue depth (Phase 2)
    success_rate: dict[str, float]  # fed by SuccessLearner / observability (Phase 5)
```
Routing becomes a scored decision, not a string-prefix match:
```python
def select_agent(task_type, context) -> str:
    candidates = [c for c in registry.all() if task_type in c.task_types]
    return max(candidates, key=lambda c: (
        c.success_rate.get(task_type, 0.5) * W_SUCCESS
        + c.confidence_by_task_type.get(task_type, 0.5) * W_CONF
        - normalized(c.current_load) * W_LOAD
    )).agent_id
```
The existing heuristic classifier (`_classify_subtask_mode`, prefix/keyword lists) doesn't disappear — it becomes one *feature* feeding the scorer (a fast, free signal) rather than the entire routing decision, and the LLM fallback becomes a tie-breaker only when the top two candidates score within an epsilon of each other, not the default path for every "unsure" case.

### 4b. Strict planner → executor → verifier → recovery cycle

`ai/agents/planning/agent.py` (Planner) must always produce a **task graph** (DAG of `AgentTask`s with `parent_task_id` links, already partially supported by the field existing in `types.py`) rather than a flat list — each node carries `success_criteria` (Phase 0).

Execution loop (new `modules/execution/orchestrator.py`, replacing ad hoc calls currently inside `CoordinatorAgent._handle_execute_goal`):
```
for each ready node in topological order:
    agent = capability_registry.select_agent(node.task_type, goal_state)
    result = await bus.dispatch(node.as_task(agent), timeout=node.timeout)
    verification = await bus.dispatch(make_verify_task(node, result), target="verifier_agent")
    if verification.success:
        mark_node_done(node, result)
    else:
        await bus.dispatch(make_recovery_task(node, result, verification), target="recovery_agent")
        # recovery agent decides: retry-with-modified-strategy | fallback-agent | re-plan
```
Verification is **mandatory** on every node, not optional — this is the "not strict enough yet" gap called out in the review. `verification.agent.py` already exists as a stub-ish specialist; it becomes the only place `success_criteria` from Phase 0 is actually evaluated.

### 4c. Recovery as first-class (review item 8)

`ai/agents/recovery/agent.py` gets a fixed internal pipeline instead of ad hoc handling:
1. **Classify** the error (`timeout`, `tool_failure`, `verification_failed`, `capability_gap`, `external_service_down`) — reuse `RecoveryEngine` (`modules/execution/recovery_engine.py`, already referenced by `CoordinatorAgent`) as the classifier backbone.
2. **Select fallback agent** via `CapabilityRegistry` excluding the agent that just failed for this `task_type`.
3. **Re-plan** if the classification implies the *plan* was wrong, not just the *execution* (e.g. `capability_gap` → send back to Planner with the failure context attached, not just retry the same node).
4. **Retry with modified strategy** (different tool, smaller step, different prompt) for transient classes (`timeout`, `tool_failure`).
5. **Final verification** — recovery output re-enters the same Verifier step from 4b; recovery never marks a node "done" on its own authority.

### 4d. True specialists (review item 9)

Given the existing agent list (`coordinator`, `supervisor`, `verification`, `planning`, `research`, `interaction`, `browser`, `integration`, `debugging`, `vision`, `coding`, `recovery`, `language`, `memory`, `execution`), tighten boundaries rather than rename everything:
- `interaction` + `execution` currently overlap on "run a grounded/deterministic task" (both appear in `_handle_route_subtask`) — merge into one `browser_operator` / `desktop_operator` pair split by target surface (web vs OS), each with a narrow `task_types` set in the capability registry.
- `supervisor` and `coordinator` overlap conceptually (routing vs overseeing) — `coordinator` keeps routing (4a), `supervisor` becomes the orchestrator loop's home (4b) so there is one place, not two, deciding "what happens next."
- `memory` becomes the only agent allowed to write `LongTermMemory` (Phase 3) — enforced by the bus only accepting `STORE_EPISODIC`/`RUN_MAINTENANCE` task types on the `memory_agent` stream.

**Exit criteria:** `tests/agents/test_coordinator_agent.py` extended to assert routing decisions change when a candidate agent's `success_rate` or `current_load` changes, not just when its keyword matches.

---

## Phase 5 — Observability that drives decisions

Review item 10. `modules/observability/trace.py` (`TraceSpan`, already used in `events/bus.py`) currently only logs. Extend it to write structured, queryable records (append to a lightweight store — SQLite/Postgres table or a Redis time-series — keyed by `agent_id, task_type, success, confidence, duration_ms, cost_usd`) and expose:
- `success_rate(agent_id, task_type)` and `avg_confidence(agent_id, task_type)` — feed directly into `CapabilityRegistry` (4a).
- `error_class_histogram(agent_id)` — feeds Recovery's classifier (4c) so recurring failure modes get flagged for a fallback-agent bias, not just handled reactively per-incident.
- A simple dashboard endpoint under `api/routes/observability.py` (already exists) exposing these aggregates, so a human can see *why* the router made a given choice — this also makes the routing scorer in 4a debuggable rather than a black box.

**Exit criteria:** killing an agent's success rate synthetically (inject failing results in a test) measurably shifts routing away from it within N task cycles, verified by a test.

---

## Migration sequencing & risk control

Because this is a running codebase with existing tests (`tests/agents/*`, `tests/unit/test_extreme_bus.py`), do **not** big-bang rewrite. Suggested order, each landing behind a feature flag so the old path stays available until the new one is proven:

1. Phase 0 (contracts) — additive, no behavior change, can land immediately.
2. Phase 1 (real `RedisBus`) — additive; `AgentBus` (in-process) stays the default until Redis path is soak-tested.
3. Phase 2 (concurrency/backpressure/cancellation) — layered onto whichever bus is active via `AbstractBus`, so it benefits both backends immediately.
4. Phase 3 (state split) — highest risk of behavior change since `WorldStateManager` is read from many call sites; do this incrementally, one call site at a time, with the old singleton kept as a deprecated shim that logs a warning on use until the migration is complete.
5. Phase 4 (planner/executor/verifier/recovery loop + capability routing) — depends on 0–3 being in place; this is where the actual "swarm" behavior change is visible to users, so gate it behind a `SWARM_ORCHESTRATOR_V2` flag and run it in shadow mode (compute both old and new routing decisions, log divergence) before cutting over.
6. Phase 5 (observability feeding decisions) — layered on top once 4 is live, since it needs real traffic through the new loop to have data to learn from.

## New/changed file map (summary)

```
apps/backend/ai/contracts/            # NEW — Phase 0: Envelope, MessageKind, versioned AgentTask/AgentResult
apps/backend/modules/bus/redis_bus.py # REWRITE — Phase 1: real XADD/XREADGROUP/XACK/XCLAIM/DLQ
apps/backend/modules/bus/base_bus.py  # EXTEND — Phase 2: cancel(), backpressure signal in dispatch()
apps/backend/modules/state/           # NEW — Phase 3: SessionState, GoalState, ExecutionContext
apps/backend/modules/execution/world_state.py  # SHRINK — Phase 3: becomes SystemSnapshotProvider (read-only)
apps/backend/container.py             # RESTRICT — Phase 3: only composition root imports this
apps/backend/modules/execution/capability_registry.py  # NEW — Phase 4a
apps/backend/modules/execution/orchestrator.py          # NEW — Phase 4b (planner→executor→verifier→recovery)
apps/backend/ai/agents/coordinator/agent.py   # SIMPLIFY — Phase 4a: routing delegates to CapabilityRegistry
apps/backend/ai/agents/recovery/agent.py      # EXTEND — Phase 4c: fixed classify→fallback→replan→retry→verify pipeline
apps/backend/modules/observability/trace.py   # EXTEND — Phase 5: structured store + aggregate queries
apps/backend/api/routes/observability.py      # EXTEND — Phase 5: expose routing/success aggregates
```

---

### Immediate next step

Start with Phase 0 + Phase 1 in parallel — they're independent, low-risk, and unblock every other phase (nothing else can be built reliably on a bus that still returns `"not implemented"`). Want me to scaffold the `ai/contracts/` package and the rewritten `RedisBus` as actual code against this repo?