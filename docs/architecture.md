# JARVIS Architecture Documentation

This document describes the target modular architecture of the **JARVIS Multi-Agent Control Center**. 

---

## 1. System Topology

JARVIS is built as a multi-speed learning system that coordinates 14 specialist AI agents. It uses:
1. **FastAPI** for core HTTP API, WebSockets, and integration.
2. **Flask** to serve the static frontend control center.
3. **LiveKit WebRTC** for real-time streaming voice agent interaction.
4. **AgentBus** for in-memory pub/sub agent communication.
5. **Dependency Injection (DI)** container (`ServiceContainer`) for runtime wiring and service lifecycle.

---

## 2. Directory Structure

```
d:/Jarvis/
├── apps/
│   ├── backend/                          # Python backend (FastAPI + LiveKit)
│   │   ├── main.py                       # Entry point — starts Flask and FastAPI
│   │   ├── agent.py                      # LiveKit agent wiring
│   │   ├── container.py                  # DI container wiring for singletons
│   │   │
│   │   ├── api/                          # HTTP FastAPI Layer
│   │   │   ├── app.py                    # FastAPI app factory
│   │   │   ├── dependencies.py           # API dependency inject
│   │   │   └── routes/                   # API Route definitions
│   │   │
│   │   ├── server/                       # Flask frontend serving
│   │   │   └── flask_app.py
│   │   │
│   │   ├── config/                       # Configuration settings
│   │   │
│   │   ├── domain/                       # Domain models
│   │   │   └── models.py
│   │   │
│   │   ├── events/                       # Event infrastructure (AgentBus)
│   │   │   └── bus.py
│   │   │
│   │   ├── ai/                           # AI Agents Layer
│   │   │   └── agents/                   # Agent implementations
│   │   │
│   │   ├── tools/                        # Builtin Tools Layer
│   │   │
│   │   ├── modules/                      # Business Logic Modules
│   │   │   ├── memory/                   # Short-term and long-term memory system
│   │   │   ├── learning/                 # Two-speed learning, experience replay
│   │   │   ├── knowledge/                # Knowledge graphs and conflict resolution
│   │   │   ├── security/                 # Policy tiers and destructive path safeguards
│   │   │   ├── planning/                 # Task and goal management
│   │   │   ├── task/                     # Task status boards and announcers
│   │   │   ├── execution/                # Execution and recovery engine
│   │   │   ├── filesystem/               # Indexing, Watchers, and Document parsing
│   │   │   ├── vision/                   # OCR, screen captures, UI mapping
│   │   │   ├── language/                 # Translation and language detection
│   │   │   ├── controls/                 # OS controllers (keyboard, mouse, window)
│   │   │   ├── skills/                   # Custom executable skill registries
│   │   │   ├── observability/            # Cost estimation and tracing
│   │   │   └── shared/                   # Shared infrastructure utilities
│   │   │
│   │   └── tests/                        # Automated Test Suite
│   │       ├── unit/                     # Isolated unit tests
│   │       ├── integration/              # Real DB & integration tests
│   │       ├── agents/                   # Agent routing & bus tests
│   │       └── modules/                  # Module logic integration tests
│   │
│   └── frontend/                         # Frontend Application (HTML/CSS/JS)
│       ├── index.html                    # Shell HTML
│       ├── styles/                       # CSS split by feature
│       └── js/                           # JS split by feature
│
├── scripts/                              # Operational & smoke-test scripts
└── infra/                                # Docker & Compose configuration files
```

---

## 3. Core Architectural Modules

### 3.1 Dependency Injection (`container.py`)
All major services are wired lazily via `ServiceContainer`. This prevents importing heavy ML/Vision libraries at load-time unless they are actively resolved. Services are registered with startup priorities so that foundational structures (like tracing and event bus) are initialized before higher-level agents.

### 3.2 Event Bus (`events/bus.py`)
The event bus coordinates communication across agents. Agents do not invoke one another directly. They publish and subscribe to `AgentTask` and `AgentResult` objects, guarding against cycles and enforcing timeout policies.

### 3.3 Security Manager (`modules/security/`)
Enforces authorization policies on destructive action categories (e.g. `delete`, `power`, `shell` commands). It works on three tiers:
- **TIER_SAFE**: Automatically allowed.
- **TIER_CONFIRM**: Prompts user for approval.
- **TIER_FORBIDDEN**: Disallowed path or bypass category.

### 3.4 Memory System (`modules/memory/`)
Provides hierarchical storage combining in-memory, relational SQLite, and vector databases (ChromaDB) to manage context across conversation threads.

---

## 4. Operational Runbook

* **Local Development Run**: `start_jarvis.bat` starts the voice assistant.
* **Backend Unit Tests**: Run `pytest tests/` in virtual environment.
* **Recreatable Smoke Test**: Run `python scripts/smoke_test.py` to assert health checks for all 13 agents on the bus.
