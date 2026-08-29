import asyncio
import sys
import os
import time
from datetime import datetime, timedelta

# Adjust path to find modules inside apps/backend
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "backend"))
sys.path.insert(0, backend_dir)

from config.settings import load_config
load_config()

from container import build_container
from modules.shared.session_manager import SessionManager
from modules.memory.consolidator import MemoryConsolidator

async def run_test():
    print("==================================================")
    print("JARVIS Cross-Session Memory Smoke Test")
    print("==================================================")

    # 1. Build container and startup
    print("\n[1] Building Service Container...")
    container = build_container()
    await container.startup()
    print("-> Container services started.")

    memory = container.get("memory")
    session_mgr = container.get("session_manager")

    if not isinstance(session_mgr, SessionManager):
        print("FAILED: session_manager service not resolved correctly.")
        sys.exit(1)
    print("-> Resolved MemoryManager and SessionManager.")

    # 2. Start Session 1
    print("\n[2] Starting Session 1...")
    session_id_1 = session_mgr.start_session(project="smoke_test_1")
    print(f"-> Session 1 ID: {session_id_1}")

    # 3. Log a few turns to Session 1
    print("\n[3] Logging conversation turns...")
    turns = [
        ("user", "I want to build a React application using vite."),
        ("assistant", "I can help with React and Vite development. What component should we build first?"),
        ("user", "Let's create a sleek navbar component."),
        ("assistant", "Perfect. Let's design a responsive navbar using React and CSS.")
    ]

    for role, text in turns:
        # Call log_conversation (which enqueues writes)
        memory.log_conversation(role=role, content=text, session_id=session_id_1)
    
    # Wait for the background writer to process logs
    print("Waiting for database writes to persist...")
    await asyncio.sleep(2)

    # Verify turns logged
    transcript_1 = memory.get_session_transcript(session_id_1)
    print(f"-> Transcript retrieved: {len(transcript_1)} turns logged.")
    if len(transcript_1) != 4:
        print(f"FAILED: Expected 4 turns, got {len(transcript_1)}")
        sys.exit(1)

    # 4. Close Session 1 & Generate Summarization
    print("\n[4] Ending Session 1 and generating summary...")
    session_mgr.end_session("graceful_exit")
    
    # Wait for session close write
    await asyncio.sleep(1)

    # Run extractive summarization manually to mimic SupervisorAgent background task
    consolidator = MemoryConsolidator(memory)
    rows = []
    for i, turn in enumerate(transcript_1):
        rows.append((i, turn["role"], turn["content"], 3))
    
    clusters = consolidator._cluster_by_topic(rows)
    cluster_summaries = []
    topics_found = []
    for topic, entries in clusters.items():
        summary = consolidator._extractive_summary(topic, entries)
        if summary:
            cluster_summaries.append(summary)
            if topic != "General":
                topics_found.append(topic)
                
    final_summary = "\n\n".join(cluster_summaries)
    topics_str = ", ".join(topics_found) if topics_found else "General"
    
    print(f"-> Generated Summary:\n{final_summary}")
    print(f"-> Topics: {topics_str}")

    # Write summary to database
    def _sync_write_summary(sid, summ, tops):
        with memory._lock.write_lock():
            memory.dbs["conversations"].execute(
                "UPDATE sessions SET summary = ?, topics = ? WHERE session_id = ?",
                (summ, tops, sid),
            )
            memory._commit()
            
    memory.enqueue_write(_sync_write_summary, session_id_1, final_summary, topics_str)
    await asyncio.sleep(1)

    # 5. Start Session 2 & Retrieve Last Session Context
    print("\n[5] Starting Session 2 and checking prompt injection...")
    session_id_2 = session_mgr.start_session(project="smoke_test_2")
    print(f"-> Session 2 ID: {session_id_2}")

    # Get last session context (should include summary and last turns due to recency < 2h)
    last_context = memory.get_last_session_context()
    print("-> Retrieved Last Session Context Block:")
    print("--------------------------------------------------")
    print(last_context)
    print("--------------------------------------------------")
    
    if "PREVIOUS SESSION" not in last_context or "React" not in last_context:
        print("FAILED: Last session context block did not contain session details or summaries.")
        sys.exit(1)

    # 6. Test on-demand Recall Past Session Tool logic
    print("\n[6] Testing on-demand recall past session search...")
    # Search for "vite"
    recall_result = memory.recall_past_sessions(query="vite", when="today")
    print("-> Recall Result for 'vite':")
    print(recall_result)
    if "React" not in recall_result:
        print("FAILED: recall_past_sessions did not find matching text in transcript.")
        sys.exit(1)

    # 7. Test Nightly Maintenance (Backfill and Prune)
    print("\n[7] Testing Nightly Maintenance backfill and pruning...")
    import uuid
    temp_session_id = f"temp_missing_summary_session_{uuid.uuid4()}"
    with memory._lock.write_lock():
        memory.dbs["conversations"].execute(
            "INSERT INTO sessions (session_id, started_at, ended_at, project) VALUES (?, ?, ?, 'smoke')",
            (temp_session_id, memory._now(), memory._now())
        )
        # Log 4 turns for it
        for i, (role, text) in enumerate(turns):
            memory.dbs["conversations"].execute(
                "INSERT INTO conversations (timestamp, role, content, session_id, importance) VALUES (?, ?, ?, ?, ?)",
                (memory._now(), role, text, temp_session_id, 3)
            )
        memory._commit()

    # Trigger backfill
    print("Triggering backfill pass...")
    consolidator._backfill_missing_session_summaries()
    
    # Assert that temp session now has summary
    with memory._lock.read_lock():
        row = memory.dbs["conversations"].execute(
            "SELECT summary FROM sessions WHERE session_id = ?",
            (temp_session_id,)
        ).fetchone()
    
    if not row or not row[0]:
        print("FAILED: backfill_missing_session_summaries did not generate summary.")
        sys.exit(1)
    print("-> Backfill successfully generated missing summaries.")

    # Trigger pruning with 0 days retention to prune all old entries except immune (importance >= 7)
    print("Triggering pruning pass with 0 retention days...")
    os.environ["JARVIS_CONVO_RETENTION_DAYS"] = "0"
    
    # Add an immune turn to Session 1
    with memory._lock.write_lock():
        memory.dbs["conversations"].execute(
            "INSERT INTO conversations (timestamp, role, content, session_id, importance) VALUES (?, ?, ?, ?, ?)",
            (memory._now(), "user", "CRITICAL KEYWORD PRESERVATION TURN", session_id_1, 8)
        )
        memory._commit()

    consolidator._prune_expired_sessions()
    
    # Assert that normal turns of session 1 were deleted (since they had importance 3),
    # but the immune turn remains.
    with memory._lock.read_lock():
        convo_rows = memory.dbs["conversations"].execute(
            "SELECT content, importance FROM conversations WHERE session_id = ?",
            (session_id_1,)
        ).fetchall()
        
    print(f"-> Conversations remaining for Session 1: {len(convo_rows)}")
    for r in convo_rows:
        print(f"   - Importance {r[1]}: {r[0]}")
        
    for content, importance in convo_rows:
        if importance < 7:
            print(f"FAILED: low-importance turn was not pruned: {content} (importance {importance})")
            sys.exit(1)
            
    contents = [r[0] for r in convo_rows]
    if "CRITICAL KEYWORD PRESERVATION TURN" not in contents:
        print("FAILED: Pruning deleted the immune turn.")
        sys.exit(1)
        
    print("-> Pruning correctly preserved only immune high-importance turns.")

    print("\n[8] Testing immediate session learning pass...")
    try:
        memory.lifecycle.run_session_learning()
        print("-> Immediate session learning completed successfully.")
    except Exception as e:
        print(f"FAILED: immediate session learning failed: {e}")
        sys.exit(1)

    print("\n==================================================")
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_test())
