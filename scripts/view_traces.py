import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "..", "apps", "backend", "database", "traces.db")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("PRAGMA table_info(spans)")
    columns = [col[1] for col in cursor.fetchall()]
    
    # Query last 30 spans
    cursor.execute("SELECT * FROM spans ORDER BY start_time DESC LIMIT 30")
    rows = cursor.fetchall()
    
    print("\nLast 30 Spans in database:")
    for row in rows:
        row_dict = dict(zip(columns, row))
        # Format start_time as local time or readable format
        import datetime
        start_dt = datetime.datetime.fromtimestamp(row_dict.get('start_time'))
        print(f"[{start_dt}] Trace: {row_dict.get('trace_id')[:8]} | Agent: {row_dict.get('agent_id')} | Task: {row_dict.get('task_type')} | Success: {row_dict.get('success')} | Duration: {row_dict.get('duration_ms')/1000:.2f}s | Error: {row_dict.get('error')}")
except Exception as e:
    print("Error:", e)
finally:
    conn.close()
