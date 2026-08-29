  async function authenticateFastAPI(apiKey) {
    if (apiKey && apiKey.split('.').length === 3) {
      jwtToken = apiKey;
      localStorage.setItem('jarvis_jwt_token', jwtToken);
      return true;
    }
    try {
      const response = await fetch(`${apiBase}/api/auth/token`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ api_key: apiKey })
      });
      
      if (!response.ok) {
        throw new Error(`FastAPI token endpoint returned ${response.status}`);
      }
      
      const data = await response.json();
      jwtToken = data.token;
      
      // Store locally
      localStorage.setItem('jarvis_jwt_token', jwtToken);
      return true;
    } catch (err) {
      console.error('FastAPI Authentication failed:', err);
      showError('Failed to establish API session on port 8000.');
      return false;
    }
  }

  // --- WebSocket Task Tracker ---
  async function loadTasks() {
    try {
      const res = await fetch(`${apiBase}/api/tasks`, {
        headers: getHeaders()
      });
      if (!res.ok) return;
      const data = await res.json();
      renderTasksList(data.tasks);
    } catch (e) {
      console.error('Failed listing tasks:', e);
    }
  }

  async function submitTaskCommand() {
    let input = taskCommandInput.value.trim();
    if (!input) return;
    
    btnSubmitTask.disabled = true;
    btnSubmitTask.querySelector('span').textContent = 'QUEUING...';
    
    try {
      if (selectedFile) {
        btnSubmitTask.querySelector('span').textContent = 'UPLOADING...';
        
        // 1. Read and upload file content
        const base64Content = await readFileAsBase64(selectedFile);
        const uploadRes = await fetch(`${apiBase}/api/upload`, {
          method: 'POST',
          headers: getHeaders(),
          body: JSON.stringify({
            filename: selectedFile.name,
            content: base64Content
          })
        });
        
        if (!uploadRes.ok) {
          const errData = await uploadRes.json();
          throw new Error(errData.detail || 'File upload failed.');
        }
        
        const uploadData = await uploadRes.json();
        const filepath = uploadData.filepath; // D:\Jarvis\uploads\filename
        
        // 2. Prep command with file location details
        input = `Please analyze the file uploaded at "${filepath}". Command action: ${input}`;
      }
      
      btnSubmitTask.querySelector('span').textContent = 'DEPLOYING...';
      const res = await fetch(`${apiBase}/api/tasks`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ input: input })
      });
      
      if (!res.ok) {
        throw new Error(`Failed to submit task. Server returned ${res.status}`);
      }
      
      // Clear inputs
      taskCommandInput.value = '';
      if (selectedFile) {
        selectedFile = null;
        fileUploader.value = '';
        attachmentPreview.classList.add('hidden');
      }
      
      loadTasks();
    } catch (e) {
      alert(e.message);
    } finally {
      btnSubmitTask.disabled = false;
      btnSubmitTask.querySelector('span').textContent = 'DEPLOY';
    }
  }

  async function cancelTask(taskId) {
    try {
      const res = await fetch(`${apiBase}/api/tasks/${taskId}`, {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (!res.ok) {
        throw new Error('Failed to cancel task.');
      }
      loadTasks();
    } catch (e) {
      alert(e.message);
    }
  }

  async function loadSwarmAgents() {
    swarmAgentsContainer.innerHTML = '<div class="loading-spinner">Warming up registry bus...</div>';
    try {
      const res = await fetch(`${apiBase}/api/agents`, {
        headers: getHeaders()
      });
      if (!res.ok) return;
      const data = await res.json();
      cachedSwarmAgents = data.agents;
      renderSwarmAgentsFiltered();
    } catch (e) {
      swarmAgentsContainer.innerHTML = `<div class="error-msg">Failed to query agent registry: ${e.message}</div>`;
    }
  }

  async function loadWorkflowsAndSchedules() {
    workflowsListContainer.innerHTML = '<div class="loading-spinner">Fetching workflows...</div>';
    schedulesListContainer.innerHTML = '<div class="loading-spinner">Fetching schedules...</div>';
    
    try {
      // 1. Load workflows
      const wfRes = await fetch(`${apiBase}/api/workflows`, { headers: getHeaders() });
      if (!wfRes.ok) throw new Error('Workflows query failed.');
      const wfData = await wfRes.json();
      window.cachedWorkflows = wfData.workflows || [];
      
      // Update schedule form options
      schedWfSelect.innerHTML = '<option value="">-- Select Deployment --</option>' + 
        wfData.workflows.map(w => `<option value="${escapeHtml(w.id)}">${escapeHtml(w.name)}</option>`).join('');
      
      // Render Workflows
      if (wfData.workflows.length === 0) {
        workflowsListContainer.innerHTML = '<div class="no-data-msg">No workflows defined yet.</div>';
      } else {
        workflowsListContainer.innerHTML = wfData.workflows.map(wf => {
          const steps = wf.steps || [];
          const stepsHtml = steps.map((s, idx) => {
            const stepName = escapeHtml(s.name || s.action || 'Step');
            const arrow = idx < steps.length - 1 ? '<span class="wf-step-arrow">→</span>' : '';
            return `<span class="wf-step-dot" title="${escapeHtml(s.agent || 'specialist')}">${stepName}</span>${arrow}`;
          }).join('');
          
          return `
            <div class="wf-item js-open-inspector" data-inspector-type="workflow" data-wf-id="${escapeHtml(wf.id)}">
              <div class="wf-info">
                <h4>${escapeHtml(wf.name)}</h4>
                <div class="wf-steps-tags">${stepsHtml}</div>
              </div>
              <div class="wf-actions">
                <button class="btn-small-play" data-id="${escapeHtml(wf.id)}" title="Run Workflow">
                  <svg viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                </button>
                <button class="btn-small-delete btn-delete-wf" data-id="${escapeHtml(wf.id)}" title="Delete Workflow">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                </button>
              </div>
            </div>
          `;
        }).join('');
        
        // Bind play/delete workflow buttons
        workflowsListContainer.querySelectorAll('.btn-small-play').forEach(btn => {
          btn.addEventListener('click', () => runWorkflow(btn.getAttribute('data-id')));
        });
        workflowsListContainer.querySelectorAll('.btn-delete-wf').forEach(btn => {
          btn.addEventListener('click', () => deleteWorkflow(btn.getAttribute('data-id')));
        });
      }
      
      // 1.1 Render Workflows inside the new Workflows Library Tab too
      if (workflowsLibraryListContainer) {
        if (wfData.workflows.length === 0) {
          workflowsLibraryListContainer.innerHTML = '<div class="no-data-msg">No custom workflows imported yet.</div>';
        } else {
          workflowsLibraryListContainer.innerHTML = wfData.workflows.map(wf => {
            const steps = wf.steps || [];
            const stepsHtml = steps.map((s, idx) => {
              const stepName = escapeHtml(s.name || s.action || 'Step');
              const arrow = idx < steps.length - 1 ? '<span class="wf-step-arrow">→</span>' : '';
              return `<span class="wf-step-dot" title="${escapeHtml(s.agent || 'specialist')}">${stepName}</span>${arrow}`;
            }).join('');
            
            return `
              <div class="wf-item js-open-inspector" data-inspector-type="workflow" data-wf-id="${escapeHtml(wf.id)}">
                <div class="wf-info">
                  <h4>${escapeHtml(wf.name)}</h4>
                  <div class="wf-steps-tags">${stepsHtml}</div>
                </div>
                <div class="wf-actions">
                  <button class="btn-small-play" data-id="${escapeHtml(wf.id)}" title="Run Workflow">
                    <svg viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                  </button>
                  <button class="btn-small-delete btn-delete-wf" data-id="${escapeHtml(wf.id)}" title="Delete Workflow">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                  </button>
                </div>
              </div>
            `;
          }).join('');
          
          // Bind play/delete workflow buttons for library container
          workflowsLibraryListContainer.querySelectorAll('.btn-small-play').forEach(btn => {
            btn.addEventListener('click', () => runWorkflow(btn.getAttribute('data-id')));
          });
          workflowsLibraryListContainer.querySelectorAll('.btn-delete-wf').forEach(btn => {
            btn.addEventListener('click', () => deleteWorkflow(btn.getAttribute('data-id')));
          });
        }
      }
      
      // 2. Load schedules
      const schedRes = await fetch(`${apiBase}/api/schedules`, { headers: getHeaders() });
      if (!schedRes.ok) throw new Error('Schedules query failed.');
      const schedData = await schedRes.json();
      
      if (schedData.schedules.length === 0) {
        schedulesListContainer.innerHTML = '<div class="no-data-msg">No active scheduled cron tasks.</div>';
      } else {
        schedulesListContainer.innerHTML = schedData.schedules.map(sch => {
          const targetWf = wfData.workflows.find(w => w.id === sch.workflow_id);
          const targetName = targetWf ? targetWf.name : sch.workflow_id;
          
          return `
            <div class="sched-item">
              <div class="sched-info">
                <h4>${escapeHtml(sch.name)}</h4>
                <div class="sched-meta">Cron: ${escapeHtml(sch.cron)} | Target: ${escapeHtml(targetName)}</div>
              </div>
              <div class="sched-actions">
                <button class="btn-small-delete btn-delete-sched" data-id="${escapeHtml(sch.id)}" title="Delete Schedule">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                </button>
              </div>
            </div>
          `;
        }).join('');
        
        // Bind delete schedule buttons
        schedulesListContainer.querySelectorAll('.btn-delete-sched').forEach(btn => {
          btn.addEventListener('click', () => deleteSchedule(btn.getAttribute('data-id')));
        });
      }
      
    } catch (e) {
      workflowsListContainer.innerHTML = `<div class="error-msg">${escapeHtml(e.message)}</div>`;
      schedulesListContainer.innerHTML = `<div class="error-msg">${escapeHtml(e.message)}</div>`;
    }
  }

  async function loadSkills() {
    skillsListContainer.innerHTML = '<div class="loading-spinner">Fetching skills...</div>';
    
    try {
      const res = await fetch(`${apiBase}/api/skills`, { headers: getHeaders() });
      if (!res.ok) throw new Error('Failed to query skills.');
      const data = await res.json();
      
      if (data.skills.length === 0) {
        skillsListContainer.innerHTML = '<div class="no-data-msg">No skills registered in the system.</div>';
      } else {
        skillsListContainer.innerHTML = data.skills.map(sk => {
          const isCustom = sk.source === 'custom';
          const badgeClass = isCustom ? 'badge-custom' : 'badge-builtin';
          const badgeText = isCustom ? 'CUSTOM' : 'SYSTEM';
          
          let actionButtons = '';
          if (isCustom) {
            const toggleChecked = sk.enabled ? 'checked' : '';
            actionButtons = `
              <div style="display: flex; align-items: center; gap: 0.5rem;">
                <label class="toggle-switch" style="position: relative; display: inline-block; width: 40px; height: 20px;">
                  <input type="checkbox" class="skill-toggle-input" data-id="${escapeHtml(sk.id)}" ${toggleChecked} style="opacity: 0; width: 0; height: 0;">
                  <span class="toggle-slider" style="position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: rgba(255,255,255,0.1); border-radius: 20px; transition: .4s;"></span>
                </label>
                <button class="btn-small-delete btn-delete-skill" data-id="${escapeHtml(sk.id)}" title="Delete Custom Skill">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 14px; height: 14px;"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                </button>
              </div>
            `;
          }
          
          const triggersHtml = sk.trigger && sk.trigger.length > 0
            ? `<div class="skill-triggers" style="margin-top: 0.5rem; display: flex; flex-wrap: wrap; gap: 0.25rem;">
                ${sk.trigger.map(t => `<span class="badge" style="font-size: 0.7rem; background: rgba(255,255,255,0.05);">${escapeHtml(t)}</span>`).join('')}
               </div>`
            : '';

          return `
            <div class="wf-item" style="display: flex; justify-content: space-between; align-items: flex-start; padding: 1rem; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; margin-bottom: 0.75rem;">
              <div class="wf-info" style="flex: 1; min-width: 0;">
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem;">
                  <h4 style="margin: 0; font-size: 1rem;">${escapeHtml(sk.name)}</h4>
                  <span class="badge ${badgeClass}" style="font-size: 0.65rem; font-weight: bold; padding: 2px 6px; border-radius: 4px;">${badgeText}</span>
                </div>
                <p class="description" style="margin: 0; font-size: 0.85rem; color: rgba(255,255,255,0.7); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(sk.description)}">${escapeHtml(sk.description)}</p>
                ${triggersHtml}
              </div>
              <div class="wf-actions" style="display: flex; align-items: center; margin-left: 1rem; align-self: center;">
                ${actionButtons}
              </div>
            </div>
          `;
        }).join('');
        
        // Bind event listeners
        skillsListContainer.querySelectorAll('.skill-toggle-input').forEach(input => {
          input.addEventListener('change', async (e) => {
            const skillId = input.getAttribute('data-id');
            const enabled = input.checked;
            try {
              const toggleRes = await fetch(`${apiBase}/api/skills/${skillId}`, {
                method: 'PATCH',
                headers: getHeaders(),
                body: JSON.stringify({ enabled })
              });
              if (!toggleRes.ok) {
                input.checked = !enabled; // Revert
                throw new Error('Failed to toggle skill.');
              }
            } catch (err) {
              alert(err.message);
            }
          });
        });
        
        skillsListContainer.querySelectorAll('.btn-delete-skill').forEach(btn => {
          btn.addEventListener('click', async () => {
            const skillId = btn.getAttribute('data-id');
            if (confirm("Are you sure you want to delete this custom skill? This cannot be undone.")) {
              try {
                const delRes = await fetch(`${apiBase}/api/skills/${skillId}`, {
                  method: 'DELETE',
                  headers: getHeaders()
                });
                if (!delRes.ok) throw new Error('Failed to delete skill.');
                loadSkills();
              } catch (err) {
                alert(err.message);
              }
            }
          });
        });
      }
    } catch (err) {
      skillsListContainer.innerHTML = `<div class="error-msg">${escapeHtml(err.message)}</div>`;
    }
  }

  async function createWorkflow(e) {
    e.preventDefault();
    const name = wfNameInput.value.trim();
    let steps = [];
    try {
      steps = JSON.parse(wfStepsInput.value);
      if (!Array.isArray(steps)) throw new Error("JSON must be a step array.");
    } catch (err) {
      alert(`Invalid Steps JSON: ${err.message}`);
      return;
    }
    
    try {
      const res = await fetch(`${apiBase}/api/workflows`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ name, steps })
      });
      if (!res.ok) throw new Error('Create workflow request failed.');
      wfNameInput.value = '';
      wfStepsInput.value = '';
      
      // Reset visual builder
      workflowSteps = [];
      renderBuilderSteps();
      
      loadWorkflowsAndSchedules();
    } catch (err) {
      alert(err.message);
    }
  }

  async function runWorkflow(wfId) {
    try {
      const res = await fetch(`${apiBase}/api/workflows/${wfId}/run`, {
        method: 'POST',
        headers: getHeaders()
      });
      if (!res.ok) throw new Error('Run workflow request failed.');
      alert('Workflow execution queued successfully!');
    } catch (err) {
      alert(err.message);
    }
  }

  async function deleteWorkflow(wfId) {
    if (!confirm('Are you sure you want to delete this workflow?')) return;
    try {
      const res = await fetch(`${apiBase}/api/workflows/${wfId}`, {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (!res.ok) throw new Error('Delete workflow request failed.');
      loadWorkflowsAndSchedules();
    } catch (err) {
      alert(err.message);
    }
  }

  async function createSchedule(e) {
    e.preventDefault();
    const name = schedNameInput.value.trim();
    const cron = schedCronInput.value.trim();
    const workflow_id = schedWfSelect.value;
    
    if (!workflow_id) {
      alert('Please select a target workflow.');
      return;
    }
    
    try {
      const res = await fetch(`${apiBase}/api/schedules`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ name, cron, workflow_id })
      });
      if (!res.ok) throw new Error('Deploy schedule request failed.');
      schedNameInput.value = '';
      schedCronInput.value = '';
      schedWfSelect.value = '';
      cronPreviewText.textContent = 'Every minute';
      loadWorkflowsAndSchedules();
    } catch (err) {
      alert(err.message);
    }
  }

  async function deleteSchedule(schedId) {
    if (!confirm('Are you sure you want to delete this schedule?')) return;
    try {
      const res = await fetch(`${apiBase}/api/schedules/${schedId}`, {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (!res.ok) throw new Error('Delete schedule request failed.');
      loadWorkflowsAndSchedules();
    } catch (err) {
      alert(err.message);
    }
  }

  // --- Visual Workflow Builder Actions ---
  const builderAgentSelect = document.getElementById('builder-agent-select');
  const builderActionInput = document.getElementById('builder-action-input');
  const builderNameInput = document.getElementById('builder-name-input');
  const builderArgsInput = document.getElementById('builder-args-input');
  const btnAddBuilderStep = document.getElementById('btn-add-builder-step');
  const builderStepsList = document.getElementById('builder-steps-list');

  if (btnAddBuilderStep) {
    btnAddBuilderStep.addEventListener('click', () => {
      const agent = builderAgentSelect.value;
      const action = builderActionInput.value.trim() || 'execute_command';
      const name = builderNameInput.value.trim() || `${agent.replace('_agent', '')}: ${action}`;
      let args = {};
      
      const argsText = builderArgsInput.value.trim();
      if (argsText) {
        try {
          args = JSON.parse(argsText);
        } catch (e) {
          alert('Step arguments must be valid JSON object: ' + e.message);
          return;
        }
      }
      
      workflowSteps.push({
        name: name,
        agent: agent,
        action: action,
        payload: args
      });
      
      // Reset builder step fields
      builderActionInput.value = '';
      builderNameInput.value = '';
      builderArgsInput.value = '';
      
      renderBuilderSteps();
    });
  }

  async function loadApprovals() {
    try {
      const res = await fetch(`${apiBase}/api/approvals`, {
        headers: getHeaders()
      });
      if (!res.ok) return;
      const data = await res.json();
      renderApprovalsList(data.approvals);
    } catch (e) {
      console.error('Failed to list approvals:', e);
    }
  }

  async function resolveApproval(approvalId, approve) {
    const action = approve ? 'approve' : 'deny';
    const reason = prompt(`Enter optional security reason for '${action}':`) || '';
    
    try {
      const res = await fetch(`${apiBase}/api/approvals/${approvalId}/${action}`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ reason })
      });
      if (!res.ok) {
        throw new Error(`Failed to resolve approval item.`);
      }
      loadApprovals();
    } catch (err) {
      alert(err.message);
    }
  }

  async function loadObservabilityData() {
    loadMetrics();
    loadAgentPerformance();
    loadTraceSpans();
  }

  async function loadMetrics() {
    try {
      const res = await fetch(`${apiBase}/api/observability/metrics`, {
        headers: getHeaders()
      });
      if (!res.ok) return;
      const data = await res.json();
      
      valTotalTasks.textContent = data.total_tasks_24h ?? '0';
      valSuccessRate.textContent = `${data.success_rate_24h ?? 0}%`;
      valAvgDuration.textContent = `${((data.avg_duration_ms ?? 0) / 1000).toFixed(1)}s`;
      valTotalTokens.textContent = data.total_tokens_24h ?? '0';
      valTotalCost.textContent = `$${(data.total_cost_usd_24h ?? 0).toFixed(4)}`;
      valAvgConfidence.textContent = (data.avg_confidence ?? 0).toFixed(2);
    } catch (e) {
      console.error('Failed to load dashboard metrics:', e);
    }
  }

  async function loadAgentPerformance() {
    try {
      const res = await fetch(`${apiBase}/api/observability/agents`, {
        headers: getHeaders()
      });
      if (!res.ok) return;
      const data = await res.json();
      
      if (!data.agents || data.agents.length === 0) {
        agentPerformanceTbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #6B7280; font-family: var(--font-mono);">No agent metrics catalogued.</td></tr>';
        return;
      }
      
      agentPerformanceTbody.innerHTML = data.agents.map(a => {
        const cleanName = escapeHtml(a.agent_id.replace('Agent', '').replace('_agent', ''));
        return `
          <tr>
            <td data-label="Agent ID"><strong>${cleanName}</strong></td>
            <td data-label="Runs">${Number(a.runs) || 0}</td>
            <td data-label="Success Rate" style="color: ${a.success_rate >= 80 ? 'var(--c-success)' : (a.success_rate >= 50 ? 'var(--c-warning)' : 'var(--c-danger)')}">
              <strong>${(Number(a.success_rate) || 0).toFixed(1)}%</strong>
            </td>
            <td data-label="Avg Duration">${((Number(a.avg_ms) || 0) / 1000).toFixed(2)}s</td>
            <td data-label="Tokens">${Number(a.tokens) || 0}</td>
            <td data-label="Confidence">${(Number(a.avg_confidence) || 0).toFixed(2)}</td>
          </tr>
        `;
      }).join('');
    } catch (e) {
      console.error('Failed to load agent performance table:', e);
    }
  }

  async function loadTraceSpans() {
    traceSpansTbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: #6B7280; font-family: var(--font-mono);">Reading telemetry database...</td></tr>';
    try {
      const res = await fetch(`${apiBase}/api/observability/spans?limit=40`, {
        headers: getHeaders()
      });
      if (!res.ok) return;
      const data = await res.json();
      
      if (!data.spans || data.spans.length === 0) {
        traceSpansTbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: #6B7280; font-family: var(--font-mono);">No traces recorded.</td></tr>';
        return;
      }
      
      traceSpansTbody.innerHTML = data.spans.map(s => {
        const isOk = s.success === 1;
        const statusHtml = isOk 
          ? '<span class="span-success">SUCCESS</span>' 
          : '<span class="span-failure">FAILED</span>';
        
        const cleanAgentId = escapeHtml((s.agent_id || '').replace('Agent', '').replace('_agent', ''));
        const spanId = escapeHtml((s.span_id || '').substring(0, 8));
        const taskType = escapeHtml(s.task_type || 'task');
        const errText = s.error ? escapeHtml(s.error.substring(0, 40) + (s.error.length > 40 ? '...' : '')) : '—';
        return `
          <tr>
            <td data-label="Span ID">${spanId}</td>
            <td data-label="Agent ID"><strong>${cleanAgentId}</strong></td>
            <td data-label="Task Type">${taskType}</td>
            <td data-label="Status">${statusHtml}</td>
            <td data-label="Duration">${((Number(s.duration_ms) || 0) / 1000).toFixed(2)}s</td>
            <td data-label="Tokens / Cost">${Number(s.tokens_used) || 0} / $${(Number(s.cost_usd) || 0).toFixed(4)}</td>
            <td data-label="Confidence">${(Number(s.confidence) || 0).toFixed(2)}</td>
            <td data-label="Telemetry Error" style="color: var(--c-danger); font-size: 11px;">${errText}</td>
          </tr>
        `;
      }).join('');
    } catch (e) {
      traceSpansTbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--c-danger);">Error loading telemetry traces: ${escapeHtml(e.message)}</td></tr>`;
    }
  }

  // --- Notifications Fetching & Rendering ---
  async function loadNotifications() {
    try {
      const res = await fetch(`${apiBase}/api/notifications`, {
        headers: getHeaders()
      });
      if (!res.ok) return;
      const data = await res.json();
      renderNotifications(data.notifications);
    } catch (e) {
      console.error('Failed to list notifications:', e);
    }
  }

  function resetNotificationsBadge() {
    unreadNotificationsCount = 0;
    syncNotificationsBadge(0, true);
  }

  // --- Cron Translator Preview Helper ---
  function translateCron(cronStr) {
    const parts = cronStr.trim().split(/\s+/);
    if (parts.length !== 5) return 'Invalid cron expression (must be 5 fields)';
    const [min, hour, dom, month, dow] = parts;
    
    if (min === '*' && hour === '*' && dom === '*' && month === '*' && dow === '*') {
      return 'Every minute';
    }
    if (min.startsWith('*/') && hour === '*' && dom === '*' && month === '*' && dow === '*') {
      return `Every ${min.slice(2)} minutes`;
    }
    if (min !== '*' && hour === '*' && dom === '*' && month === '*' && dow === '*') {
      return `Every hour at minute ${min}`;
    }
    if (min !== '*' && hour !== '*' && dom === '*' && month === '*' && dow === '*') {
      const formattedHour = hour.padStart(2, '0');
      const formattedMin = min.padStart(2, '0');
      return `Daily at ${formattedHour}:${formattedMin}`;
    }
    return `Cron trigger: [${escapeHtml(cronStr)}]`;
  }
