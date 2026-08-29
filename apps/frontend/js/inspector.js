/**
 * JARVIS Inspector Panel
 * Contextual right-side drawer showing full detail for a selected Task, Agent, or Workflow.
 * Opens via delegated click on any element carrying class "js-open-inspector".
 * Looks up full records from window.cachedTasksList / window.cachedSwarmAgents / window.cachedWorkflows,
 * which are populated by tasks.js and api.js during normal rendering — no extra network calls.
 */

document.addEventListener('DOMContentLoaded', () => {
  const panel = document.getElementById('inspector-panel');
  const backdrop = document.getElementById('inspector-backdrop');
  const titleEl = document.getElementById('inspector-title');
  const kindEl = document.getElementById('inspector-kind');
  const bodyEl = document.getElementById('inspector-body');
  const btnClose = document.getElementById('btn-inspector-close');

  if (!panel) return; // markup not present, skip silently

  function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function openInspector() {
    panel.classList.add('open');
    backdrop.classList.remove('hidden');
    requestAnimationFrame(() => backdrop.classList.add('open'));
  }

  function closeInspector() {
    panel.classList.remove('open');
    backdrop.classList.remove('open');
    setTimeout(() => backdrop.classList.add('hidden'), 250);
  }
  window.closeInspector = closeInspector;

  function fieldRow(label, value) {
    if (value === undefined || value === null || value === '') return '';
    return `
      <div class="inspector-field-row">
        <span class="inspector-field-label">${escapeHtml(label)}</span>
        <span class="inspector-field-value">${value}</span>
      </div>
    `;
  }

  function statusPill(status) {
    const s = (status || 'unknown').toLowerCase();
    return `<span class="inspector-status-pill status-${escapeHtml(s)}">${escapeHtml(s)}</span>`;
  }

  function rawJsonBlock(obj) {
    return `
      <details class="inspector-raw-json">
        <summary>Raw JSON</summary>
        <pre>${escapeHtml(JSON.stringify(obj, null, 2))}</pre>
      </details>
    `;
  }

  // ── Task inspector ────────────────────────────────────────────────────
  function renderTaskDetail(task) {
    titleEl.textContent = task.label || task.task_type || 'Task';
    kindEl.textContent = 'TASK';

    const createdStr = task.created_at ? new Date(task.created_at).toLocaleString() : '—';
    const updatedStr = task.updated_at ? new Date(task.updated_at).toLocaleString() : '—';

    let resultBlock = '';
    if (task.error) {
      resultBlock = `<div class="inspector-section-title">ERROR</div><pre class="inspector-error-block">${escapeHtml(task.error)}</pre>`;
    } else if (task.result) {
      resultBlock = `<div class="inspector-section-title">RESULT</div><pre class="inspector-result-block">${escapeHtml(typeof task.result === 'object' ? JSON.stringify(task.result, null, 2) : task.result)}</pre>`;
    }

    bodyEl.innerHTML = `
      <div class="inspector-status-row">
        ${statusPill(task.status)}
        <span class="badge-tag priority-${escapeHtml(task.priority || 'normal')}">${escapeHtml(task.priority || 'normal')}</span>
      </div>

      <div class="inspector-progress-block">
        <div class="task-progress-container">
          <div class="task-progress-bar ${task.status === 'running' ? 'running' : ''}" style="width: ${task.progress || 0}%"></div>
        </div>
        <span class="task-progress-pct">${task.progress || 0}%</span>
      </div>

      <div class="inspector-fields">
        ${fieldRow('Task ID', `<code>${escapeHtml(task.task_id)}</code>`)}
        ${fieldRow('Type', escapeHtml(task.task_type))}
        ${fieldRow('Owner Agent', escapeHtml(task.owner_agent || task.agent))}
        ${fieldRow('Created', createdStr)}
        ${fieldRow('Updated', updatedStr)}
      </div>

      ${resultBlock}
      ${rawJsonBlock(task)}
    `;

    if (task.status === 'running' || task.status === 'queued') {
      bodyEl.insertAdjacentHTML('beforeend', `
        <div class="inspector-actions">
          <button class="btn-secondary inspector-cancel-btn" data-id="${escapeHtml(task.task_id)}">Halt Task</button>
        </div>
      `);
      bodyEl.querySelector('.inspector-cancel-btn').addEventListener('click', () => {
        if (typeof cancelTask === 'function') cancelTask(task.task_id);
      });
    }
  }

  // ── Agent inspector ───────────────────────────────────────────────────
  function renderAgentDetail(agent) {
    const cleanName = (agent.name || '').replace('Agent', '');
    titleEl.textContent = cleanName || agent.name || 'Agent';
    kindEl.textContent = 'AGENT';

    const capsHtml = (agent.capabilities || []).map(cap => `<span class="cap-tag">${escapeHtml(cap)}</span>`).join('') || '<span class="cap-tag">speak</span>';

    bodyEl.innerHTML = `
      <div class="inspector-status-row">
        ${statusPill(agent.status)}
      </div>

      <p class="inspector-description">${escapeHtml(agent.description || 'No description registered.')}</p>

      <div class="inspector-fields">
        ${fieldRow('Full Name', escapeHtml(agent.name))}
        ${fieldRow('Current Job', escapeHtml(agent.current_job) || '<span class="inspector-muted">idle</span>')}
        ${fieldRow('Queue Depth', agent.queue_depth ?? agent.queue ?? 0)}
        ${fieldRow('Latency (ms)', agent.latency_ms ?? agent.latency)}
        ${fieldRow('Confidence', agent.confidence != null ? `${Math.round(agent.confidence * 100)}%` : null)}
        ${fieldRow('Success Rate', agent.success_rate != null ? `${Math.round(agent.success_rate * 100)}%` : null)}
      </div>

      <div class="inspector-section-title">REGISTERED ACTIONS</div>
      <div class="capabilities-list">${capsHtml}</div>

      ${rawJsonBlock(agent)}
    `;
  }

  // ── Workflow inspector ────────────────────────────────────────────────
  function renderWorkflowDetail(wf) {
    titleEl.textContent = wf.name || 'Workflow';
    kindEl.textContent = 'WORKFLOW';

    const steps = wf.steps || [];
    const stepsRows = steps.map((s, idx) => `
      <tr>
        <td>${idx + 1}</td>
        <td>${escapeHtml((s.agent || '').replace('_agent', ''))}</td>
        <td>${escapeHtml(s.action || s.name || '—')}</td>
        <td><code>${escapeHtml(s.args ? JSON.stringify(s.args) : '{}')}</code></td>
      </tr>
    `).join('');

    let dagHtml = '';
    if (typeof buildWorkflowDagSvg === 'function') {
      dagHtml = `
        <div class="inspector-section-title">EXECUTION GRAPH</div>
        <div class="inspector-dag-wrap scrollable-y">${buildWorkflowDagSvg(wf)}</div>
      `;
    }

    bodyEl.innerHTML = `
      <div class="inspector-fields">
        ${fieldRow('Workflow ID', `<code>${escapeHtml(wf.id)}</code>`)}
        ${fieldRow('Step Count', steps.length)}
      </div>

      ${dagHtml}

      <div class="inspector-section-title">STEPS</div>
      <div class="inspector-table-wrap scrollable-y">
        <table class="inspector-table">
          <thead><tr><th>#</th><th>Agent</th><th>Action</th><th>Payload</th></tr></thead>
          <tbody>${stepsRows || '<tr><td colspan="4" class="inspector-muted">No steps defined.</td></tr>'}</tbody>
        </table>
      </div>

      <div class="inspector-actions">
        <button class="btn-primary inspector-run-btn" data-id="${escapeHtml(wf.id)}">Run Workflow</button>
        <button class="btn-secondary inspector-delete-btn" data-id="${escapeHtml(wf.id)}">Delete</button>
      </div>

      ${rawJsonBlock(wf)}
    `;

    bodyEl.querySelector('.inspector-run-btn').addEventListener('click', () => {
      if (typeof runWorkflow === 'function') runWorkflow(wf.id);
    });
    bodyEl.querySelector('.inspector-delete-btn').addEventListener('click', () => {
      if (typeof deleteWorkflow === 'function') deleteWorkflow(wf.id);
      closeInspector();
    });
  }

  // ── Dispatch ───────────────────────────────────────────────────────────
  function openForTask(taskId) {
    const task = (window.cachedTasksList || []).find(t => String(t.task_id) === String(taskId));
    if (!task) return;
    renderTaskDetail(task);
    openInspector();
  }

  function openForAgent(agentName) {
    const agent = (window.cachedSwarmAgents || []).find(a => a.name === agentName);
    if (!agent) return;
    renderAgentDetail(agent);
    openInspector();
  }

  function openForWorkflow(wfId) {
    const wf = (window.cachedWorkflows || []).find(w => String(w.id) === String(wfId));
    if (!wf) return;
    renderWorkflowDetail(wf);
    openInspector();
  }

  // Delegated click listener — survives re-renders of task/agent/workflow lists
  document.addEventListener('click', (e) => {
    // Ignore clicks on interactive controls inside a card (buttons, links, inputs)
    if (e.target.closest('button, a, input, select, textarea')) return;

    const el = e.target.closest('.js-open-inspector');
    if (!el) return;

    const type = el.getAttribute('data-inspector-type');
    if (type === 'task') openForTask(el.getAttribute('data-task-id'));
    else if (type === 'agent') openForAgent(el.getAttribute('data-agent-name'));
    else if (type === 'workflow') openForWorkflow(el.getAttribute('data-wf-id'));
  });

  if (btnClose) btnClose.addEventListener('click', closeInspector);
  if (backdrop) backdrop.addEventListener('click', closeInspector);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && panel.classList.contains('open')) closeInspector();
  });
});
