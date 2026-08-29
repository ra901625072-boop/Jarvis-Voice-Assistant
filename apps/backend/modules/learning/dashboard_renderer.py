import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("JARVIS.DashboardRenderer")

class DashboardRenderer:
    @staticmethod
    def render_cli_report(mm) -> str:
        # Query stats
        with mm._lock:
            db = mm.dbs["conversations"]
            tot_events = db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0]
            tot_recs = db.execute("SELECT COUNT(*) FROM learning_recommendations").fetchone()[0]
            tot_gaps = db.execute("SELECT COUNT(*) FROM agent_skill_gaps").fetchone()[0]
            tot_curr = db.execute("SELECT COUNT(*) FROM curriculum_items WHERE active = 1").fetchone()[0]
            
            pending_recs = db.execute(
                "SELECT id, target_agent, recommendation_type, payload_json FROM learning_recommendations WHERE status = 'pending' LIMIT 5"
            ).fetchall()
            
            recent_audit = db.execute(
                "SELECT id, change_type, status, created_at FROM learning_audit_log ORDER BY id DESC LIMIT 5"
            ).fetchall()

        report = f"""# JARVIS Self-Learning Dashboard Report
Generated At: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 📊 Summary Metrics
- **Total Learning Events**: {tot_events}
- **Total Generated Recommendations**: {tot_recs}
- **Open Skill Gaps**: {tot_gaps}
- **Active Curriculum Items**: {tot_curr}

## 🔔 Pending Recommendations (Top 5)
"""
        if not pending_recs:
            report += "No pending recommendations.\n"
        for r in pending_recs:
            report += f"- **ID #{r[0]}** for *{r[1]}* ({r[2]}): {r[3][:120]}...\n"

        report += "\n## 📝 Recent Audited Changes (Top 5)\n"
        if not recent_audit:
            report += "No audited changes found.\n"
        for a in recent_audit:
            report += f"- **Audit #{a[0]}** | {a[1]} | Status: `{a[2]}` | {a[3]}\n"
            
        return report

    @staticmethod
    def generate_static_html(mm, output_path: str = None) -> str:
        if not output_path:
            # Save to apps/backend/logs/learning_dashboard.html
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            logs_dir = os.path.join(base_dir, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            output_path = os.path.join(logs_dir, "learning_dashboard.html")

        # Query metrics
        with mm._lock:
            db = mm.dbs["conversations"]
            tot_events = db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0]
            tot_recs = db.execute("SELECT COUNT(*) FROM learning_recommendations").fetchone()[0]
            tot_gaps = db.execute("SELECT COUNT(*) FROM agent_skill_gaps").fetchone()[0]
            tot_curr = db.execute("SELECT COUNT(*) FROM curriculum_items WHERE active = 1").fetchone()[0]
            
            pending_recs = db.execute(
                "SELECT id, target_agent, recommendation_type, payload_json, created_at FROM learning_recommendations WHERE status = 'pending' ORDER BY id DESC LIMIT 15"
            ).fetchall()
            
            active_curr = db.execute(
                "SELECT id, agent_id, curriculum_type, prompt, created_at FROM curriculum_items WHERE active = 1 ORDER BY id DESC LIMIT 15"
            ).fetchall()

            recent_audit = db.execute(
                "SELECT id, change_type, status, created_at, notes, before_state, after_state FROM learning_audit_log ORDER BY id DESC LIMIT 15"
            ).fetchall()

            capabilities = db.execute(
                "SELECT agent_id, task_type, ema_score, success_rate, total_runs FROM agent_capability_scores ORDER BY ema_score ASC LIMIT 10"
            ).fetchall()

        # Build records lists for template injection
        recs_html = ""
        for r in pending_recs:
            recs_html += f"""
            <div class="card card-rec">
                <span class="badge badge-pending">PENDING</span>
                <h3>ID #{r[0]} - {r[1]}</h3>
                <p class="type">Type: <strong>{r[2]}</strong> | Created: {r[4]}</p>
                <pre><code>{json.dumps(json.loads(r[3]), indent=2)}</code></pre>
            </div>
            """
        if not pending_recs:
            recs_html = "<p class='no-data'>No pending recommendations found.</p>"

        curr_html = ""
        for c in active_curr:
            curr_html += f"""
            <div class="card card-curr">
                <span class="badge badge-active">ACTIVE</span>
                <h3>{c[1]} - {c[2]}</h3>
                <p class="desc">{c[3]}</p>
                <p class="date">Created: {c[4]}</p>
            </div>
            """
        if not active_curr:
            curr_html = "<p class='no-data'>No active training curriculum items.</p>"

        audit_html = ""
        for a in recent_audit:
            audit_html += f"""
            <tr class="audit-row">
                <td>#{a[0]}</td>
                <td><span class="type-tag">{a[1]}</span></td>
                <td><span class="status-tag status-{a[2]}">{a[2].upper()}</span></td>
                <td>{a[3]}</td>
                <td>{a[4]}</td>
            </tr>
            """
        if not recent_audit:
            audit_html = "<tr><td colspan='5' class='no-data'>No audit entries found.</td></tr>"

        caps_html = ""
        for cp in capabilities:
            score = round((cp[2] or 0.0) * 100)
            success = round((cp[3] or 0.0) * 100)
            score_class = "score-high" if score >= 90 else ("score-low" if score <= 60 else "score-medium")
            caps_html += f"""
            <div class="cap-item">
                <div class="cap-header">
                    <strong>{cp[0]}</strong>
                    <span class="cap-task">{cp[1]}</span>
                </div>
                <div class="progress-container">
                    <div class="progress-bar {score_class}" style="width: {score}%"></div>
                </div>
                <div class="cap-meta">
                    <span>Live Confidence: {score}%</span>
                    <span>Success Rate: {success}% ({cp[4]} runs)</span>
                </div>
            </div>
            """
        if not capabilities:
            caps_html = "<p class='no-data'>No capability scores seeded.</p>"

        # Premium sleek HTML dashboard template
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JARVIS Swarm Self-Learning Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-base: #0a0d14;
            --bg-surface: #121622;
            --bg-card: #181d2e;
            --accent: #3a86ff;
            --accent-glow: rgba(58, 134, 255, 0.15);
            --text-main: #f0f3fa;
            --text-muted: #8e9bb8;
            --border: #222b40;
            --success: #06d6a0;
            --warning: #ffd166;
            --danger: #ef476f;
        }}
        
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-base);
            color: var(--text-main);
            padding: 2rem;
            line-height: 1.5;
        }}

        header {{
            margin-bottom: 2.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 1.5rem;
        }}

        h1 {{
            font-size: 2.5rem;
            font-weight: 800;
            background: linear-gradient(135deg, #3a86ff, #00f5d4);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .time {{
            color: var(--text-muted);
            font-size: 0.95rem;
            background-color: var(--bg-surface);
            padding: 0.5rem 1rem;
            border-radius: 30px;
            border: 1px solid var(--border);
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1.5rem;
            margin-bottom: 3rem;
        }}

        .stat-card {{
            background-color: var(--bg-surface);
            padding: 1.5rem;
            border-radius: 16px;
            border: 1px solid var(--border);
            text-align: center;
            position: relative;
            overflow: hidden;
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .stat-card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
        }}

        .stat-val {{
            font-size: 3rem;
            font-weight: 800;
            margin-top: 0.5rem;
            color: var(--accent);
            text-shadow: 0 0 10px rgba(58, 134, 255, 0.3);
        }}

        .stat-label {{
            color: var(--text-muted);
            text-transform: uppercase;
            font-size: 0.8rem;
            letter-spacing: 1px;
            font-weight: 600;
        }}

        .main-layout {{
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 2rem;
            margin-bottom: 3rem;
        }}

        @media (max-width: 1024px) {{
            .main-layout {{
                grid-template-columns: 1fr;
            }}
        }}

        section {{
            background-color: var(--bg-surface);
            border-radius: 20px;
            border: 1px solid var(--border);
            padding: 2rem;
            margin-bottom: 2rem;
        }}

        h2 {{
            font-size: 1.5rem;
            margin-bottom: 1.5rem;
            border-left: 4px solid var(--accent);
            padding-left: 0.75rem;
            font-weight: 600;
        }}

        .cards-list {{
            display: flex;
            flex-direction: column;
            gap: 1.25rem;
        }}

        .card {{
            background-color: var(--bg-card);
            border-radius: 12px;
            padding: 1.5rem;
            border: 1px solid var(--border);
            position: relative;
        }}

        .badge {{
            position: absolute;
            top: 1.25rem;
            right: 1.5rem;
            font-size: 0.7rem;
            font-weight: 800;
            padding: 0.25rem 0.6rem;
            border-radius: 30px;
            letter-spacing: 0.5px;
        }}

        .badge-pending {{
            background-color: rgba(255, 209, 102, 0.15);
            color: var(--warning);
        }}

        .badge-active {{
            background-color: rgba(6, 214, 160, 0.15);
            color: var(--success);
        }}

        .card h3 {{
            font-size: 1.15rem;
            margin-bottom: 0.5rem;
            padding-right: 6rem;
        }}

        .card p.type {{
            color: var(--text-muted);
            font-size: 0.85rem;
            margin-bottom: 1rem;
        }}

        pre {{
            background-color: #0b0d16;
            padding: 1rem;
            border-radius: 8px;
            overflow-x: auto;
            border: 1px solid #1a2030;
        }}

        code {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.85rem;
            color: #ff79c6;
        }}

        .cap-item {{
            margin-bottom: 1.5rem;
            padding-bottom: 1.25rem;
            border-bottom: 1px solid var(--border);
        }}

        .cap-item:last-child {{
            border-bottom: none;
            margin-bottom: 0;
            padding-bottom: 0;
        }}

        .cap-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }}

        .cap-task {{
            background-color: rgba(255,255,255,0.05);
            padding: 0.2rem 0.5rem;
            border-radius: 6px;
            font-size: 0.8rem;
            color: var(--text-muted);
        }}

        .progress-container {{
            background-color: #0b0d16;
            height: 8px;
            border-radius: 10px;
            overflow: hidden;
            margin-bottom: 0.4rem;
        }}

        .progress-bar {{
            height: 100%;
            border-radius: 10px;
        }}

        .score-high {{
            background: linear-gradient(90deg, var(--accent), var(--success));
        }}

        .score-medium {{
            background: var(--warning);
        }}

        .score-low {{
            background: var(--danger);
        }}

        .cap-meta {{
            display: flex;
            justify-content: space-between;
            font-size: 0.8rem;
            color: var(--text-muted);
        }}

        .audit-table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            margin-top: 1rem;
        }}

        .audit-table th, .audit-table td {{
            padding: 1rem;
            border-bottom: 1px solid var(--border);
        }}

        .audit-table th {{
            color: var(--text-muted);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.8rem;
            letter-spacing: 0.5px;
        }}

        .audit-row:hover {{
            background-color: rgba(255,255,255,0.02);
        }}

        .type-tag {{
            background-color: rgba(58, 134, 255, 0.15);
            color: var(--accent);
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 600;
        }}

        .status-tag {{
            font-size: 0.75rem;
            font-weight: 800;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
        }}

        .status-applied {{
            background-color: rgba(6, 214, 160, 0.15);
            color: var(--success);
        }}

        .status-rolled_back {{
            background-color: rgba(239, 71, 111, 0.15);
            color: var(--danger);
        }}

        .no-data {{
            color: var(--text-muted);
            text-align: center;
            padding: 2rem 0;
            font-style: italic;
        }}
    </style>
</head>
<body>

    <header>
        <div>
            <h1>JARVIS Self-Learning Swarm</h1>
            <p style="color: var(--text-muted); margin-top: 0.25rem;">Meta-Learning & Swarm Self-Improvement Loop Control</p>
        </div>
        <div class="time">Last Updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
    </header>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-label">Telemetry Events</div>
            <div class="stat-val">{tot_events}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Recommendations</div>
            <div class="stat-val">{tot_recs}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Skill Gaps</div>
            <div class="stat-val">{tot_gaps}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Active Curriculum</div>
            <div class="stat-val">{tot_curr}</div>
        </div>
    </div>

    <div class="main-layout">
        <div class="left-col">
            <section>
                <h2>Pending Recommendations</h2>
                <div class="cards-list">
                    {recs_html}
                </div>
            </section>

            <section>
                <h2>Active Curriculum</h2>
                <div class="cards-list">
                    {curr_html}
                </div>
            </section>
        </div>

        <div class="right-col">
            <section>
                <h2>Agent Capability Model</h2>
                <div class="caps-list">
                    {caps_html}
                </div>
            </section>
        </div>
    </div>

    <section>
        <h2>Recent Audited Changes</h2>
        <table class="audit-table">
            <thead>
                <tr>
                    <th>Audit ID</th>
                    <th>Change Type</th>
                    <th>Status</th>
                    <th>Applied At</th>
                    <th>Description</th>
                </tr>
            </thead>
            <tbody>
                {audit_html}
            </tbody>
        </table>
    </section>

</body>
</html>
"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        logger.info(f"DashboardRenderer: Wrote static dashboard to {output_path}")
        return output_path
