# JARVIS Voice Assistant

JARVIS is a real-time, voice-enabled assistant designed using a multi-agent orchestration architecture. It relies on **LiveKit** for real-time WebRTC audio sessions, **FastAPI** for core API routing, **Flask** for serving the frontend client, and a two-speed learning loop backed by **SQLite** and **ChromaDB**.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.12+
- `npx` (Node Package Manager for MCP tools)
- API Keys: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `JARVIS_API_KEY`, and `GEMINI_API_KEY` (configured in `.env`)

### Running the System
The easiest way to start both the backend and frontend is by running the launcher script:
```bash
start_jarvis.bat
```
This launcher will:
1. Activate the Python virtual environment and start the **JARVIS Backend Server** (`apps/backend/main.py`) which exposes the FastAPI API at `http://localhost:8000` and the LiveKit RTC agent.
2. Start the **JARVIS Frontend Server** via a Python HTTP server at `http://localhost:5173`.

---

## 📁 Repository Structure

The workspace is organized as follows:

```
d:/Jarvis/
├── apps/
│   ├── backend/                 # FastAPI/LiveKit Backend application
│   │   ├── ai/
│   │   │   └── agents/          # Multi-agent orchestrator & specialist agents
│   │   ├── api/                 # API routing and middleware
│   │   ├── config/              # Server configuration and settings
│   │   ├── database/            # Ignored runtime sqlite/chroma database folders
│   │   ├── domain/              # Domain entities (e.g. models)
│   │   ├── integrations/        # External service connectors
│   │   ├── modules/             # Core memory, planning, database, and skill systems
│   │   ├── server/              # Flask application wrapper serving frontend
│   │   ├── tests/               # Pytest automated testing suite
│   │   └── tools/builtin/       # Built-in capability tools (files, system, media, etc.)
│   └── frontend/                # Frontend application client (index.html, styles.css, app.js)
├── database/                    # SQLite database files (`traces.db`, `memory.db`)
├── docs/                        # Architectural documentation
│   └── realtime_learning_architecture.md  # Real-time learning details
├── examples/                    # Developer guides & exercises
│   └── agent_exercise_guide.md  # Guided scenarios to run and train specialist agents
└── check_learning_status.py     # Monitoring dashboard CLI tool
```

---

## 🤖 Multi-Agent Orchestration

JARVIS uses a **Supervisor Agent** (architect) to route and coordinate commands to 13 specialist agents on the message bus (14 agents total in the system):

| Agent | Responsibility | Key Task Types |
|---|---|---|
| **Supervisor** | Main coordinator, handles session state and routing | `speak`, `supervisor_routing`, `supervisor_session` |
| **Coordinator** | Generates context, analyzes failures, evaluates plans | `generate_context`, `analyze_failure`, `evaluate_plan` |
| **Planning** | Creates step-by-step plans for complex actions | `create_plan`, `replan` |
| **Execution** | Executes plan steps, queries world state | `execute_plan`, `get_world_state` |
| **Verification** | Validates results against constraints | `verify_result` |
| **Recovery** | Self-heals and runs recovery procedures on failure | `recover_failure` |
| **Memory** | Stores execution reports and checks memory health | `record_execution_report`, `replay`, `memory_health_check` |
| **Browser** | Automates browser tasks and retrieves web content | `automate_web_flow` |
| **Coding** | Refactors code, builds software projects | `refactor_code`, `build_project` |
| **Debugging** | Diagnoses errors, applies self-healing to scripts | `diagnose_error`, `apply_self_healing`, `verify_fix` |
| **Integration**| Interacts with webhooks, GraphQL, APIs | `webhook_flow`, `call_graphql`, `sync_data`, etc. |
| **Vision** | Reads screens, analyzes layouts, finds UI elements | `analyze_screen`, `find_ui_element`, `read_screen_text` |
| **Interaction**| Conducts turn-by-turn grounded perception-action loops | `run_grounded_task` |
| **Language** | Performs language detection, translation, and preference mapping | `detect_language`, `translate_text`, `extract_document_data`, `set_language_preference` |

---

## 🧠 Real-Time Learning Loop

Every specialist agent records outcomes that feed back into a **two-speed learning loop**:
- **Fast Loop:** Updates live capability scores (EMA score) and records failure streaks on the fly. Fires immediately after each task.
- **Slow Loop:** A nightly cleanup and consolidation job (`MemoryLifecycle.run_nightly` at 03:05) that recalculates ground-truth success metrics, decays old scores, and merges lessons.

### Monitoring & Seeding Tools

1. **Dashboard Monitor:** Check coverage and active failure streaks across all registered agents:
   ```bash
   python check_learning_status.py
   ```
2. **Smoke Test / Seeding:** Simulate successes and failures to verify or populate database scores without requiring active LLM/API keys:
   ```bash
   python seed_and_verify_learning.py            # run real seed
   python seed_and_verify_learning.py --dry-run  # dry run preview
   python seed_and_verify_learning.py --clean    # clean up test rows
   ```

3. **Verification & Integration Tests:**
   JARVIS features a comprehensive integration verification suite to check connectivity and end-to-end swarm execution:
   - **Specialist Reachability (Smoke Test):** Verify all 14 agents boot and register on the in-memory bus correctly:
     ```bash
     python scripts/smoke_test.py
     ```
   - **E2E Swarm Execution Test:** Simulates 5 high-level goal scenarios (deterministic plans, grounded visual routing, filesystem search, failure recovery, and concurrent dispatch) utilizing mock LLM wrappers to check the entire orchestration pipeline locally:
     ```bash
     python scripts/e2e_smoke.py
     ```

For detailed architectural information, see [realtime_learning_architecture.md](file:///d:/Jarvis/docs/realtime_learning_architecture.md).

---

## 🛠️ Codebase Guidelines for Agents

When developing or refactoring code within JARVIS:
- **Automatic Folder Creation:** Directories like `runtime/` or database folders are gitignored and automatically generated at runtime. Do not manually create empty folders unless they contain a configuration/file.
- **Preserve Comments:** Keep docstrings and code comments intact.
- **Verification:** Always run `python seed_and_verify_learning.py --dry-run` or check the pytest suite in `apps/backend/tests/` before committing.
