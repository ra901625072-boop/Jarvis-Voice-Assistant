import sqlite3
import logging

logger = logging.getLogger("JARVIS.MemorySchema")

def _safe_alter(conn: sqlite3.Connection, table: str, col: str, col_def: str) -> None:
    """Add a column to a table only if it does not already exist."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
    except sqlite3.OperationalError:
        pass  # column already exists

class MemorySchemaMixin:
    def _init_tables(self) -> None:
        with self._lock.write_lock():
            conn = self.dbs.get_conn()
            c    = conn.cursor()

            # ── Original tables (kept for backward compatibility) ─────────

            c.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT NOT NULL,
                    role        TEXT NOT NULL,
                    content     TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON conversations(timestamp)")

            # Migration: add new columns to existing conversations table
            _safe_alter(conn, "conversations", "importance",    "INTEGER DEFAULT 3")
            _safe_alter(conn, "conversations", "memory_type",   "TEXT DEFAULT 'general'")
            _safe_alter(conn, "conversations", "project",       "TEXT DEFAULT 'general'")
            _safe_alter(conn, "conversations", "consolidated",  "INTEGER DEFAULT 0")
            _safe_alter(conn, "lessons_learned", "pattern_key", "TEXT")
            _safe_alter(conn, "lessons_learned", "project",       "TEXT DEFAULT 'general'")
            _safe_alter(conn, "agent_reflections", "project",     "TEXT DEFAULT 'general'")
            _safe_alter(conn, "conversations", "session_id",      "TEXT")
            _safe_alter(conn, "session_metrics", "session_id",    "TEXT")
            c.execute("CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id)")

            c.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts
                USING fts5(content, content='conversations', content_rowid='id')
            """)
            # Triggers (safe: IF NOT EXISTS not supported for triggers, ignore errors)
            for trig_sql in [
                """CREATE TRIGGER IF NOT EXISTS conversations_ai
                   AFTER INSERT ON conversations BEGIN
                     INSERT INTO conversations_fts(rowid, content) VALUES (new.id, new.content);
                   END;""",
                """CREATE TRIGGER IF NOT EXISTS conversations_ad
                   AFTER DELETE ON conversations BEGIN
                     INSERT INTO conversations_fts(conversations_fts, rowid, content)
                     VALUES ('delete', old.id, old.content);
                   END;""",
                """CREATE TRIGGER IF NOT EXISTS conversations_au
                   AFTER UPDATE ON conversations BEGIN
                     INSERT INTO conversations_fts(conversations_fts, rowid, content)
                     VALUES ('delete', old.id, old.content);
                     INSERT INTO conversations_fts(rowid, content) VALUES (new.id, new.content);
                   END;""",
            ]:
                try:
                    c.execute(trig_sql)
                except Exception:
                    pass

            c.execute("""
                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary    TEXT NOT NULL,
                    period     TEXT DEFAULT 'daily',
                    topic      TEXT DEFAULT 'general',
                    created_at TEXT NOT NULL
                )
            """)
            _safe_alter(conn, "conversation_summaries", "period", "TEXT DEFAULT 'daily'")
            _safe_alter(conn, "conversation_summaries", "topic",  "TEXT DEFAULT 'general'")

            c.execute("""
                CREATE TABLE IF NOT EXISTS preferences (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS user_profile (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    attribute TEXT NOT NULL,
                    value     TEXT NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    email         TEXT,
                    phone_number  TEXT,
                    role          TEXT DEFAULT 'user',
                    created_at    TEXT NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    title     TEXT NOT NULL,
                    due_time  TEXT,
                    completed INTEGER DEFAULT 0
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    description TEXT NOT NULL,
                    status      TEXT DEFAULT 'pending'
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS session_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    duration REAL NOT NULL,
                    disconnect_reason TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id        TEXT PRIMARY KEY,
                    started_at        TEXT NOT NULL,
                    ended_at          TEXT,
                    disconnect_reason TEXT,
                    turn_count        INTEGER DEFAULT 0,
                    summary           TEXT,
                    topics            TEXT,
                    project           TEXT DEFAULT 'general'
                )
            """)

            # ── New tables ────────────────────────────────────────────────

            c.execute("""
                CREATE TABLE IF NOT EXISTS semantic_memories (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    content       TEXT NOT NULL,
                    importance    INTEGER DEFAULT 5,
                    project       TEXT DEFAULT 'general',
                    tags          TEXT DEFAULT '',
                    decay_score   REAL DEFAULT 1.0,
                    superseded    INTEGER DEFAULT 0,
                    superseded_by INTEGER,
                    created_at    TEXT NOT NULL,
                    updated_at    TEXT NOT NULL
                )
            """)
            _safe_alter(conn, "semantic_memories", "superseded",    "INTEGER DEFAULT 0")
            _safe_alter(conn, "semantic_memories", "superseded_by", "INTEGER")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sem_project ON semantic_memories(project)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sem_importance ON semantic_memories(importance)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sem_superseded ON semantic_memories(superseded)")

            c.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS semantic_memories_fts
                USING fts5(content, content='semantic_memories', content_rowid='id')
            """)
            for trig_sql in [
                """CREATE TRIGGER IF NOT EXISTS semantic_memories_ai
                   AFTER INSERT ON semantic_memories BEGIN
                     INSERT INTO semantic_memories_fts(rowid, content) VALUES (new.id, new.content);
                   END;""",
                """CREATE TRIGGER IF NOT EXISTS semantic_memories_ad
                   AFTER DELETE ON semantic_memories BEGIN
                     INSERT INTO semantic_memories_fts(semantic_memories_fts, rowid, content)
                     VALUES ('delete', old.id, old.content);
                   END;""",
                """CREATE TRIGGER IF NOT EXISTS semantic_memories_au
                   AFTER UPDATE ON semantic_memories BEGIN
                     INSERT INTO semantic_memories_fts(semantic_memories_fts, rowid, content)
                     VALUES ('delete', old.id, old.content);
                     INSERT INTO semantic_memories_fts(rowid, content) VALUES (new.id, new.content);
                   END;""",
            ]:
                try:
                    c.execute(trig_sql)
                except Exception:
                    pass

            c.execute("""
                CREATE TABLE IF NOT EXISTS episodic_memories (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    content     TEXT NOT NULL,
                    importance  INTEGER DEFAULT 5,
                    project     TEXT DEFAULT 'general',
                    event_date  TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_ep_event_date ON episodic_memories(event_date)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS procedural_memories (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_name    TEXT NOT NULL,
                    content       TEXT NOT NULL,
                    importance    INTEGER DEFAULT 5,
                    success_count INTEGER DEFAULT 0,
                    fail_count    INTEGER DEFAULT 0,
                    created_at    TEXT NOT NULL,
                    updated_at    TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS working_memory (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    key        TEXT UNIQUE NOT NULL,
                    value      TEXT NOT NULL,
                    expires_at TEXT,
                    updated_at TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS agent_reflections (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    reflection  TEXT NOT NULL,
                    period      TEXT DEFAULT 'daily',
                    created_at  TEXT NOT NULL,
                    project     TEXT DEFAULT 'general'
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS project_memories (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_name TEXT NOT NULL,
                    content      TEXT NOT NULL,
                    importance   INTEGER DEFAULT 5,
                    tags         TEXT DEFAULT '',
                    created_at   TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_pm_project ON project_memories(project_name)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT UNIQUE NOT NULL,
                    entity_type TEXT NOT NULL,
                    description TEXT,
                    created_at  TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS relationships (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_a   TEXT NOT NULL,
                    relation   TEXT NOT NULL,
                    entity_b   TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    UNIQUE(entity_a, relation, entity_b)
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_rel_a ON relationships(entity_a)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_rel_b ON relationships(entity_b)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS workflow_stats (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_pattern    TEXT UNIQUE NOT NULL,
                    success_count   INTEGER DEFAULT 0,
                    fail_count      INTEGER DEFAULT 0,
                    avg_exec_time_ms INTEGER DEFAULT 0,
                    last_error      TEXT,
                    updated_at      TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS agent_state (
                    id                    INTEGER PRIMARY KEY CHECK (id = 1),
                    current_goal          TEXT,
                    active_plan_json      TEXT,
                    execution_history_json TEXT,
                    screen_context_json   TEXT,
                    updated_at            TEXT NOT NULL
                )
            """)

            # ── Phase 5 tables ────────────────────────────────────────────

            c.execute("""
                CREATE TABLE IF NOT EXISTS gate_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT NOT NULL,
                    decision     TEXT NOT NULL,
                    reason       TEXT,
                    created_at   TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS lessons_learned (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    lesson           TEXT NOT NULL,
                    source_pattern   TEXT UNIQUE NOT NULL,
                    occurrence_count INTEGER DEFAULT 1,
                    importance       INTEGER DEFAULT 8,
                    created_at       TEXT NOT NULL,
                    last_triggered   TEXT NOT NULL,
                    pattern_key      TEXT,
                    project          TEXT DEFAULT 'general'
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_ll_pattern_key ON lessons_learned(pattern_key)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS active_goals (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal       TEXT NOT NULL,
                    goal_type  TEXT DEFAULT 'task',
                    parent_id  INTEGER DEFAULT NULL,
                    priority   INTEGER DEFAULT 5,
                    project    TEXT DEFAULT 'general',
                    status     TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (parent_id) REFERENCES active_goals(id) ON DELETE CASCADE
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_goals_status ON active_goals(status)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS goal_progress (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id    INTEGER NOT NULL REFERENCES active_goals(id),
                    milestone  TEXT NOT NULL,
                    status     TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS tool_memory (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name           TEXT NOT NULL,
                    success_count       INTEGER DEFAULT 0,
                    fail_count          INTEGER DEFAULT 0,
                    avg_exec_time_ms    INTEGER DEFAULT 0,
                    last_failure_reason TEXT,
                    last_used           TEXT,
                    reliability_score   REAL DEFAULT 1.0,
                    updated_at          TEXT NOT NULL,
                    context_tag         TEXT DEFAULT 'general',
                    UNIQUE(tool_name, context_tag)
                )
            """)

            # Migration for existing tool_memory table to fix UNIQUE constraint
            try:
                # Check if we need to migrate by attempting to read context_tag
                c.execute("SELECT context_tag FROM tool_memory LIMIT 1")

                # If we get here, column exists but we might need to fix the UNIQUE constraint
                # We'll just force a safe recreate
                c.execute("CREATE TABLE IF NOT EXISTS tool_memory_new (id INTEGER PRIMARY KEY AUTOINCREMENT, tool_name TEXT NOT NULL, success_count INTEGER DEFAULT 0, fail_count INTEGER DEFAULT 0, avg_exec_time_ms INTEGER DEFAULT 0, last_failure_reason TEXT, last_used TEXT, reliability_score REAL DEFAULT 1.0, updated_at TEXT NOT NULL, context_tag TEXT DEFAULT 'general', UNIQUE(tool_name, context_tag))")
                c.execute("INSERT OR IGNORE INTO tool_memory_new (id, tool_name, success_count, fail_count, avg_exec_time_ms, last_failure_reason, last_used, reliability_score, updated_at, context_tag) SELECT id, tool_name, success_count, fail_count, avg_exec_time_ms, last_failure_reason, last_used, reliability_score, updated_at, COALESCE(context_tag, 'general') FROM tool_memory")
                c.execute("DROP TABLE tool_memory")
                c.execute("ALTER TABLE tool_memory_new RENAME TO tool_memory")
            except Exception:
                pass


            c.execute("""
                CREATE TABLE IF NOT EXISTS agent_self_model (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    capability TEXT NOT NULL,
                    category   TEXT DEFAULT 'general',
                    confidence REAL DEFAULT 1.0,
                    notes      TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_self_model_cap ON agent_self_model(capability)")

            # Phase 5 migration: add superseded columns to semantic_memories
            _safe_alter(conn, "semantic_memories", "superseded",    "INTEGER DEFAULT 0")
            _safe_alter(conn, "semantic_memories", "superseded_by", "INTEGER")
            # Phase 5 migration: enrich relationships table
            _safe_alter(conn, "relationships", "source_memory",  "INTEGER")
            _safe_alter(conn, "relationships", "last_verified",  "TEXT")

            # Redesign Phase 3 dynamic migrations
            _safe_alter(conn, "episodic_memories", "goal_id", "INTEGER REFERENCES active_goals(id) ON DELETE SET NULL")
            c.execute("CREATE INDEX IF NOT EXISTS idx_ep_goal_id ON episodic_memories(goal_id)")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_proc_skill ON procedural_memories(skill_name)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sem_project_super ON semantic_memories(project, superseded)")

            # Vision System Caching and Logs Schema
            c.execute("""
                CREATE TABLE IF NOT EXISTS vision_cache (
                    image_hash TEXT,
                    prompt TEXT,
                    result TEXT,
                    created_at TEXT,
                    PRIMARY KEY (image_hash, prompt)
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS vision_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    app TEXT,
                    activity TEXT,
                    summary TEXT
                )
            """)

            # ── Agent Self-Learning Schema ────────────────────────────────

            c.execute("""
                CREATE TABLE IF NOT EXISTS agent_task_outcomes (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id        TEXT    NOT NULL,
                    task_type       TEXT    NOT NULL,
                    task_id         TEXT    NOT NULL,
                    success         INTEGER NOT NULL,
                    duration_ms     REAL    DEFAULT 0,
                    error_summary   TEXT,
                    goal_hint       TEXT,
                    created_at      TEXT    NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_ato_agent_type ON agent_task_outcomes(agent_id, task_type)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_ato_created ON agent_task_outcomes(created_at)")

            _safe_alter(conn, "tool_memory", "context_tag", "TEXT DEFAULT 'general'")
            c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tool_context ON tool_memory(tool_name, context_tag)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS agent_capability_scores (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id        TEXT NOT NULL,
                    task_type       TEXT NOT NULL,
                    success_rate    REAL NOT NULL,
                    total_runs      INTEGER NOT NULL,
                    confidence      REAL NOT NULL,
                    last_updated    TEXT NOT NULL,
                    UNIQUE(agent_id, task_type)
                )
            """)

            # --- Real-time learning: persisted failure streaks (replaces in-memory dict) ---
            c.execute("""
                CREATE TABLE IF NOT EXISTS agent_failure_streaks (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id     TEXT NOT NULL,
                    task_type    TEXT NOT NULL,
                    streak       INTEGER DEFAULT 0,
                    last_pattern TEXT,
                    updated_at   TEXT NOT NULL,
                    UNIQUE(agent_id, task_type)
                )
            """)

            # --- Success patterns: tracks proven successful workflows ---
            c.execute("""
                CREATE TABLE IF NOT EXISTS success_patterns (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal         TEXT NOT NULL UNIQUE,
                    plan_json    TEXT NOT NULL,
                    score        REAL DEFAULT 1.0,
                    use_count    INTEGER DEFAULT 1,
                    created_at   TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_sp_goal ON success_patterns(goal)")

            # --- Real-time learning: EMA confidence nudge, separate from the nightly ground-truth score ---
            _safe_alter(conn, "agent_capability_scores", "ema_score", "REAL DEFAULT 0.8")
            _safe_alter(conn, "agent_capability_scores", "last_task_id", "TEXT")

            # --- Dedicated Learning Agent Tables ---
            c.execute("""
                CREATE TABLE IF NOT EXISTS learning_events (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id        TEXT NOT NULL,
                    task_type       TEXT NOT NULL,
                    event_type      TEXT NOT NULL,
                    severity        TEXT DEFAULT 'info',
                    pattern_key     TEXT,
                    summary         TEXT,
                    created_at      TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_le_agent_type ON learning_events(agent_id, task_type)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS learning_recommendations (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_event_id    INTEGER,
                    target_agent       TEXT NOT NULL,
                    recommendation_type TEXT NOT NULL,
                    payload_json       TEXT NOT NULL,
                    status             TEXT DEFAULT 'pending',
                    created_at         TEXT NOT NULL,
                    FOREIGN KEY(source_event_id) REFERENCES learning_events(id) ON DELETE SET NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_lr_target ON learning_recommendations(target_agent)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS agent_skill_gaps (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id     TEXT NOT NULL,
                    skill_area   TEXT NOT NULL,
                    failure_rate REAL DEFAULT 0.0,
                    last_updated TEXT NOT NULL,
                    notes        TEXT,
                    UNIQUE(agent_id, skill_area)
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_asg_agent ON agent_skill_gaps(agent_id)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS curriculum_items (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id          TEXT NOT NULL,
                    curriculum_type   TEXT NOT NULL,
                    prompt            TEXT NOT NULL,
                    expected_behavior TEXT,
                    evaluation_rule   TEXT,
                    active            INTEGER DEFAULT 1,
                    created_at        TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_ci_agent ON curriculum_items(agent_id)")

            # --- Dedicated Learning Agent Hardening Schema ---
            _safe_alter(conn, "learning_events", "dedupe_key", "TEXT")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_le_dedupe ON learning_events(dedupe_key)")

            _safe_alter(conn, "learning_recommendations", "dedupe_key", "TEXT")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_lr_dedupe ON learning_recommendations(dedupe_key)")
            _safe_alter(conn, "learning_recommendations", "version", "INTEGER DEFAULT 1")
            _safe_alter(conn, "learning_recommendations", "parent_version_id", "INTEGER")

            _safe_alter(conn, "curriculum_items", "version", "INTEGER DEFAULT 1")
            _safe_alter(conn, "curriculum_items", "parent_version_id", "INTEGER")
            _safe_alter(conn, "curriculum_items", "status", "TEXT DEFAULT 'active'")

            c.execute("""
                CREATE TABLE IF NOT EXISTS learning_audit_log (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    change_type        TEXT NOT NULL, -- 'prompt_patch' or 'routing_change'
                    before_state       TEXT,
                    after_state        TEXT,
                    recommendation_id  INTEGER,
                    status             TEXT DEFAULT 'applied', -- 'applied', 'rolled_back'
                    rollback_pointer   INTEGER,
                    created_at         TEXT NOT NULL,
                    notes              TEXT
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_lal_rec ON learning_audit_log(recommendation_id)")

            # --- Real Learning Agent: Full Episodes & Trajectories ---
            c.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    episode_id      TEXT UNIQUE NOT NULL,
                    agent_id        TEXT NOT NULL,
                    task_type       TEXT NOT NULL,
                    goal            TEXT,
                    context_json    TEXT,
                    plan_json       TEXT,
                    trajectory_json TEXT,
                    outcome_json    TEXT,
                    duration_ms     REAL DEFAULT 0.0,
                    tokens_used     INTEGER DEFAULT 0,
                    cost_usd        REAL DEFAULT 0.0,
                    success         INTEGER NOT NULL,
                    evaluation_json TEXT,
                    created_at      TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_episodes_agent ON episodes(agent_id, task_type)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_episodes_success ON episodes(success)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_episodes_created ON episodes(created_at)")

            # --- Real Learning Agent: Tiered Strategies ---
            c.execute("""
                CREATE TABLE IF NOT EXISTS strategies (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    name                TEXT UNIQUE NOT NULL,
                    category            TEXT DEFAULT 'general',
                    description         TEXT NOT NULL,
                    trigger_condition   TEXT NOT NULL,
                    action_guidance     TEXT NOT NULL,
                    source_episodes_json TEXT,
                    confidence          REAL DEFAULT 0.70,
                    utility_score       REAL DEFAULT 0.50,
                    status              TEXT DEFAULT 'candidate', -- candidate, validated, trusted, permanent
                    success_count       INTEGER DEFAULT 0,
                    fail_count          INTEGER DEFAULT 0,
                    created_at          TEXT NOT NULL,
                    updated_at          TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_strategies_category ON strategies(category)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_strategies_status ON strategies(status)")

            # --- Real Learning Agent: Memory Promotion Lifecycle ---
            c.execute("""
                CREATE TABLE IF NOT EXISTS memory_promotions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type     TEXT NOT NULL, -- 'strategy', 'lesson', 'skill'
                    entity_id       TEXT NOT NULL,
                    from_status     TEXT NOT NULL,
                    to_status       TEXT NOT NULL,
                    reason          TEXT,
                    evidence_json   TEXT,
                    created_at      TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_promotions_entity ON memory_promotions(entity_type, entity_id)")

            # --- Real Learning Agent: Skill Candidates & Evolution ---
            c.execute("""
                CREATE TABLE IF NOT EXISTS skill_candidates (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_name            TEXT UNIQUE NOT NULL,
                    description           TEXT NOT NULL,
                    code_content          TEXT NOT NULL,
                    source_strategy_id    INTEGER,
                    benchmark_results_json TEXT,
                    status                TEXT DEFAULT 'draft', -- draft, tested, registered, rejected
                    created_at            TEXT NOT NULL,
                    updated_at            TEXT NOT NULL,
                    FOREIGN KEY(source_strategy_id) REFERENCES strategies(id) ON DELETE SET NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_sc_status ON skill_candidates(status)")

            # Enhance lessons_learned and procedural_memories with utility & status lifecycle
            _safe_alter(conn, "lessons_learned", "status", "TEXT DEFAULT 'validated'")
            _safe_alter(conn, "lessons_learned", "utility_score", "REAL DEFAULT 0.5")
            _safe_alter(conn, "lessons_learned", "confidence", "REAL DEFAULT 0.8")
            _safe_alter(conn, "lessons_learned", "reusability", "REAL DEFAULT 0.8")
            _safe_alter(conn, "lessons_learned", "generalization", "REAL DEFAULT 0.7")

            _safe_alter(conn, "procedural_memories", "status", "TEXT DEFAULT 'validated'")
            _safe_alter(conn, "procedural_memories", "utility_score", "REAL DEFAULT 0.5")

            conn.commit()
            logger.info("All memory tables (Phase 4 + Phase 5 + Self-Learning + Real Learning Agent) initialised.")
