# JARVIS Autonomous Memory Agent Architecture Blueprint
**Version:** 2.0  
**Target Maturity:** Level 8–9 (Adaptive, Multi-Agent Cognitive Memory)

---

## 1. Executive Vision: Memory as a Cognitive Subsystem

A production-grade Autonomous AI Assistant cannot rely on naive conversational history or static vector database lookups. Instead, memory is a **managed cognitive hierarchy** that actively governs:
1. **What to Remember** (Selection & Write Gating)
2. **How to Represent** (Hierarchical Schemas: Working, Episodic, Semantic, Procedural)
3. **Where to Store** (Polyglot Tiering: Redis, SQLite, ChromaDB, Object Storage, Knowledge Graph)
4. **When & What to Retrieve** (Multi-stage Hybrid Retrieval, Reranking, Budgeting)
5. **How to Resolve Conflicts** (Temporal Validity, Predicate Contradiction, Semantic Disambiguation)
6. **How to Consolidate & Learn** (Offline Reflection, Generalization, Workflow Learning)
7. **When to Forget** (Exponential Decay, Deduplication, Staleness Archival)
8. **How to Guard Action** (Pre-execution Policy Interception & Protected Resource Safeguards)

```
                              ┌───────────────────────────────────────┐
                              │                 USER                  │
                              └───────────────────┬───────────────────┘
                                                  │
                                                  ▼
                              ┌───────────────────────────────────────┐
                              │          JARVIS MAIN AGENT            │
                              │       (Reasoning & Planning)          │
                              └───────────────────┬───────────────────┘
                                                  │
                                 Agent Memory Bus │ (Bi-directional RPC/Events)
                                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                     MEMORY AGENT SUBSYSTEM                                      │
│                                                                                                 │
│  ┌─────────────────────────┐    ┌─────────────────────────┐    ┌─────────────────────────────┐  │
│  │     OBSERVE & GATE      │    │    HYBRID RETRIEVAL     │    │     REFLECTION & DECAY      │  │
│  │ • Noise filter (len<8)  │    │ • Query generation      │    │ • Daily reflection cycle    │  │
│  │ • Jaccard deduplication │    │ • BM25 / FTS5 search    │    │ • Success/failure pattern   │  │
│  │ • Frequency promotion   │    │ • Dense vector search   │    │ • Exponential decay engine  │  │
│  │ • Importance scoring    │    │ • Metadata & recency    │    │ • Consolidation & clustering│  │
│  │ • Conflict detection    │    │ • Cross-encoder rerank  │    │ • Memory pruning/archival   │  │
│  └────────────┬────────────┘    └────────────▲────────────┘    └──────────────┬──────────────┘  │
└───────────────┼──────────────────────────────┼────────────────────────────────┼─────────────────┘
                ▼                              │                                ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   THE 4 CORE MEMORY TIERS                                       │
│                                                                                                 │
│  ┌────────────────────┐   ┌────────────────────┐   ┌────────────────────┐   ┌────────────────┐  │
│  │   WORKING MEMORY   │   │  EPISODIC MEMORY   │   │  SEMANTIC MEMORY   │   │   PROCEDURAL   │  │
│  │                    │   │                    │   │                    │   │     MEMORY     │  │
│  │ • Active task goals│   │ • Action trajectories│ • User preferences   │   │ • Tool safety  │  │
│  │ • Current step/plan│   │ • Tool invocation logs│ • Project state facts │   │ • Workflow DAGs│  │
│  │ • Constraints budget│  │ • Failures & errors│   │ • Verified knowledge│  │ • Policy rules │  │
│  │ • Ephemeral state  │   │ • Historical replays│  │ • Domain heuristics │  │ • Best practices│ │
│  └────────────────────┘   └────────────────────┘   └────────────────────┘   └────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. The Four Core Memory Tiers

| Memory Tier | Primary Question | Persistence | Latency Target | Storage Mechanism | Example in Jarvis |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Working Memory** | *"What am I executing right now?"* | Ephemeral (Task lifetime) | $< 5\text{ ms}$ | In-Memory / Redis / Context Budget | Active goal: *“Research black holes”*, completed steps, current budget, locked resources |
| **Episodic Memory** | *"What happened in the past?"* | Long-term (Event log) | $< 30\text{ ms}$ | SQLite (`conversations`, `episodic_memories`) + ChromaDB | Episode #9281: Ran search on NASA, extracted 4 papers, attempted closing server tab, failed gracefully |
| **Semantic Memory** | *"What verified facts do I know?"* | Long-term (Consolidated) | $< 50\text{ ms}$ | SQLite (`semantic_memories` + FTS5) + ChromaDB | User preference: *“Structured Markdown with tables”*; Fact: *“Jarvis backend runs on port 8000”* |
| **Procedural Memory** | *"How should I behave & execute?"* | Long-term (Evolving rules) | $< 10\text{ ms}$ | SQLite (`workflow_patterns`, `tool_memory`, `policy_rules`) | Rule: *“Protected Browser Tab: Never close tab matching `localhost:8000` without explicit confirmation”* |

---

## 3. Cognitive Memory Lifecycle Pipeline

The memory agent executes a continuous 14-stage cognitive loop across both real-time execution and asynchronous offline maintenance:

```
[Real-Time Path]
1. OBSERVE      ──► Intercept user prompt, tool execution outputs, system errors, or plan milestones.
2. CAPTURE      ──► Extract candidates (entities, preferences, lessons, state modifications).
3. CLASSIFY     ──► Categorize into Working, Episodic, Semantic, or Procedural.
4. SCORE        ──► Compute dynamic Importance (1–10) and initial Confidence (0.0–1.0).
5. GATE         ──► Reject noise, check near-duplicates (Jaccard >= 0.82), defer low-frequency topics.
6. VALIDATE     ──► Verify source authority (Explicit User Statement vs Inferred Heuristic).
7. RESOLVE      ──► Detect predicate contradictions; mark superseded memories with lineage pointers.
8. STORE & INDEX──► Commit to SQLite tables, generate embeddings for ChromaDB, update FTS indices.

[Retrieval & Execution Path]
9. RETRIEVE     ──► Hybrid retrieval (Dense Semantic + Sparse BM25 + Exact Tag Filters).
10. RERANK      ──► Cross-score using relevance, importance, recency decay, and task scope.
11. ASSEMBLE    ──► Fit within context budget (e.g. 3,000 tokens) using strict priority hierarchies.
12. GUARD       ──► Intercept proposed tool calls against Procedural Memory safety policies.

[Offline / Reflection Path]
13. REFLECT     ──► Daily/Weekly analysis of success rates, failure clusters, and habitual patterns.
14. DECAY/PRUNE ──► Apply S(t) = S0 * exp(-lambda * t), consolidate duplicate clusters, archive stale entries.
```

---

## 4. Algorithmic Formulations

### 4.1. Importance & Confidence Formulation

$$Importance = \text{clamp}_{1..10}\Big(w_{rel} R + w_{use} U + w_{freq} F + w_{exp} E - w_{red} D - w_{vol} V\Big)$$

Where:
- $R \in [0, 10]$: Immediate relevance to the agent's core competencies.
- $U \in [0, 10]$: Expected future utility across independent sessions.
- $F \in [0, 5]$: Occurrence frequency within the sliding observation window.
- $E \in [0, 10]$: Explicitness (10 for explicit directives like *"Never do X"*, 3 for passive conversational notes).
- $D \in [0, 10]$: Semantic redundancy against existing knowledge.
- $V \in [0, 5]$: Ephemeral volatility (e.g., temporary tokens, transient counters).

### 4.2. Typed Memory Retention Policies & Temporal Decay

Rather than relying on naive importance numbers alone to determine memory longevity (which can cause temporary high-importance task details to live forever), Jarvis enforces **Typed Memory Retention Policies**:

```
Memory Retention Policy
│
├── CRITICAL SAFETY RULE (e.g. Protected Server Tabs, API Secrets)
│   └── Policy: Immutable, never decayed, zero-exception policy check
│
├── EXPLICIT USER MEMORY (e.g. "I prefer Markdown reports with tables")
│   └── Policy: Persistent until explicitly modified, superseded, or forgotten by user
│
├── PROJECT FACT (e.g. "Project Alpha backend is FastAPI")
│   └── Policy: Version + validity tracking with temporal superseding (`valid_from`, `valid_until`)
│
├── PROCEDURAL LESSON (e.g. "Always inspect project structure before editing")
│   └── Policy: Confidence + execution evidence reinforcement (promoted from reflection)
│
├── NORMAL MEMORY (e.g. General conversational context, historical exchanges)
│   └── Policy: Standard exponential decay: S(t) = S0 * exp(-lambda * t)
│
└── LOW-VALUE / NOISE MEMORY (e.g. "ok", "hi", ephemeral weather remarks)
    └── Policy: Aggressive write-gate rejection or rapid pruning (decay threshold < 0.15)
```

$$\text{DecayScore}(t) = \text{BaseImportance} \times \exp(-\lambda_{\text{policy}} \cdot \Delta t_{\text{days}})$$

- **Adaptive $\lambda$:** $\lambda = 0.0$ for Critical Safety & Explicit Preferences; $\lambda = 0.05$ for Normal Memories; $\lambda \ge 0.15$ for Transient Working Context.
- **Pruning Criterion:** Pruned when $\text{DecayScore}(t) < 0.15$ and not refreshed within the active retention window.

### 4.3. Conflict Resolution & Superseding Lineage

When a new assertion $M_{new} = \langle S, P_{new}, O_{new} \rangle$ arrives:
1. Query active memories for subject $S$: $\{M_1, M_2, \dots, M_k\}$.
2. Check semantic compatibility between $P_{new}$ and $P_i$.
3. If contradictory:
   - Mark $M_{old}.\text{superseded} = 1$
   - Set $M_{old}.\text{valid\_until} = \text{now}()$
   - Set $M_{old}.\text{superseded\_by} = M_{new}.\text{id}$
   - Set $M_{new}.\text{valid\_from} = \text{now}()$
   - Assign $M_{new}$ a recency bonus ($+1$ importance).

---

## 5. Multi-Scope Partitioning & Agent Isolation

To prevent memory pollution and cross-agent hallucination, memories are strictly partitioned across 5 hierarchical scopes:

```
┌────────────────────────────────────────────────────────┐
│ GLOBAL SCOPE (System immutable rules, safety policies) │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────┴────────────────────────────┐
│ USER SCOPE (User identity, cross-project preferences)   │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────┴────────────────────────────┐
│ PROJECT SCOPE (Project stack, architecture, conventions)│
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────┴────────────────────────────┐
│ AGENT SCOPE (Specialized learned skills, tool metrics) │
│ ├── Research Agent (Source credibility, search DAGs)   │
│ ├── Coding Agent   (AST patterns, linter workarounds)  │
│ └── Browser Agent  (Protected tab rules, DOM selectors)│
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────┴────────────────────────────┐
│ SESSION SCOPE (Working memory, active task context)    │
└────────────────────────────────────────────────────────┘
```

---

## 6. Procedural Tool Safety Interception

Memory is not merely an input to the prompt; it is an active **runtime safety guard**:

```python
async def execute_tool_with_memory_guard(tool_name: str, args: dict, memory_agent) -> ToolExecutionResult:
    # 1. Retrieve procedural safety policies matching this tool & target
    safety_policy = await memory_agent.check_tool_policy(tool_name, args)
    
    if safety_policy.is_blocked:
        return ToolExecutionResult(
            success=False,
            blocked_by_policy=True,
            reason=safety_policy.reason, # e.g. "Tab is marked IMMUTABLE: Protected Jarvis Backend"
            requires_human_approval=safety_policy.requires_hitl
        )
        
    # 2. Execute tool
    result = await tool_registry.execute(tool_name, args)
    
    # 3. Feed execution outcome back to ToolMemory & ExperienceReplay
    await memory_agent.record_tool_outcome(tool_name, success=result.success, duration=result.duration)
    return result
```

---

## 7. Maturity Assessment & Implementation Roadmap

```
Level 0: No Memory (Stateless LLM)
Level 1: Raw Chat History (Context window dumping)
Level 2: Vector DB Search (Naive similarity matching)
Level 3: Persistent Episodic Storage (Relational conversation tables)
Level 4: Typed Multi-Store (Working + Episodic + Semantic + Procedural)       ◄── [Jarvis Base]
Level 5: Write Gating & Automated Extraction                                  ◄── [Jarvis Current]
Level 6: Contradiction Resolution & Exponential Decay Consolidation           ◄── [Jarvis Current]
Level 7: Autonomous Reflection Engine & Experience Learning                   ◄── [Jarvis Current]
Level 8: Multi-Agent Scoped Memory Bus & Pre-Execution Policy Interception    ◄── [Phase 6 Target]
Level 9: Adaptive Meta-Retrieval (Dynamic query routing based on task type)   ◄── [Phase 6 Target]
Level 10: Fully Autonomous Long-Term Cognitive Self-Evolution
```

---
*Generated for the Jarvis Autonomous Assistant Cognitive Core.*
