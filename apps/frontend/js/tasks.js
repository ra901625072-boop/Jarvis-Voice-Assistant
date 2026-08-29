  function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const base64String = reader.result.split(',')[1];
        resolve(base64String);
      };
      reader.onerror = (error) => reject(error);
      reader.readAsDataURL(file);
    });
  }

  function renderTasksList(tasks) {
    const colContainers = {
      queued: document.getElementById('tasks-queued-container'),
      running: document.getElementById('tasks-running-container'),
      completed: document.getElementById('tasks-completed-container'),
      failed: document.getElementById('tasks-failed-container')
    };

    const colCounts = {
      queued: document.getElementById('count-queued'),
      running: document.getElementById('count-running'),
      completed: document.getElementById('count-completed'),
      failed: document.getElementById('count-failed')
    };

    // Reset columns
    Object.keys(colContainers).forEach(key => {
      if (colContainers[key]) colContainers[key].innerHTML = '';
    });

    if (!tasks || tasks.length === 0) {
      Object.keys(colContainers).forEach(key => {
        if (colContainers[key]) colContainers[key].innerHTML = `<div class="no-data-msg small">No tasks.</div>`;
        if (colCounts[key]) colCounts[key].textContent = '0';
      });
      syncTasksBadge(0, true);
      pillActiveTasks.classList.add('hidden');
      return;
    }

    // Cache full task list for the inspector panel to look up by id
    window.cachedTasksList = tasks;

    // Group tasks
    const grouped = {
      queued: [],
      running: [],
      completed: [],
      failed: []
    };

    tasks.forEach(task => {
      let status = task.status;
      if (status === 'queued') grouped.queued.push(task);
      else if (status === 'running') grouped.running.push(task);
      else if (status === 'completed' || status === 'done') grouped.completed.push(task);
      else if (status === 'failed' || status === 'error') grouped.failed.push(task);
      else grouped.queued.push(task); // Fallback
    });

    // Update global badges
    const activeCount = grouped.running.length + grouped.queued.length;
    if (activeCount > 0) {
      syncTasksBadge(activeCount, false);
      
      valPillTasks.textContent = activeCount;
      pillActiveTasks.classList.remove('hidden');
    } else {
      syncTasksBadge(0, true);
      pillActiveTasks.classList.add('hidden');
    }

    // Render cards for each column
    Object.keys(grouped).forEach(colKey => {
      const list = grouped[colKey];
      if (colCounts[colKey]) colCounts[colKey].textContent = list.length;

      if (!colContainers[colKey]) return;

      if (list.length === 0) {
        colContainers[colKey].innerHTML = `<div class="no-data-msg small">No tasks here.</div>`;
        return;
      }

      colContainers[colKey].innerHTML = list.map(task => {
        const priorityClass = `priority-${task.priority || 'normal'}`;
        const isRunning = task.status === 'running' || task.status === 'queued';
        
        let detailHtml = '';
        if (task.error) {
          detailHtml = `<div class="task-details error">Error: ${task.error}</div>`;
        } else if (task.result) {
          detailHtml = `<div class="task-details result">Result: ${task.result}</div>`;
        }
        
        const cancelBtnHtml = isRunning 
          ? `<button class="btn-cancel-task" data-id="${task.task_id}">HALT</button>` 
          : '';
          
        const progressClass = task.status === 'running' ? 'running' : '';
        const createdStr = task.created_at ? new Date(task.created_at).toLocaleTimeString() : '—';
        
        return `
          <div class="task-card js-open-inspector" data-inspector-type="task" data-task-id="${task.task_id}">
            <div class="task-card-header">
              <span class="task-lbl">${task.label || task.task_type}</span>
              <div class="task-meta">
                <span class="badge-tag ${priorityClass}">${task.priority}</span>
              </div>
            </div>
            
            <div class="task-progress-section">
              <div class="task-progress-container">
                <div class="task-progress-bar ${progressClass}" style="width: ${task.progress || 0}%"></div>
              </div>
              <span class="task-progress-pct">${task.progress || 0}%</span>
            </div>
            
            ${detailHtml}
            
            <div class="task-card-footer">
              <span>START: ${createdStr}</span>
              ${cancelBtnHtml}
            </div>
          </div>
        `;
      }).join('');
    });

    // Bind cancellation buttons
    Object.keys(colContainers).forEach(key => {
      if (!colContainers[key]) return;
      colContainers[key].querySelectorAll('.btn-cancel-task').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const taskId = btn.getAttribute('data-id');
          cancelTask(taskId);
        });
      });
    });
  }

  // --- Swarm Agents Loading & Filtering ---
  function renderSwarmAgentsFiltered() {
    if (!cachedSwarmAgents || cachedSwarmAgents.length === 0) {
      swarmAgentsContainer.innerHTML = '<div class="no-data-msg">No agents registered.</div>';
      return;
    }
    
    let filtered = cachedSwarmAgents;
    
    // 1. Search filter
    if (currentSwarmSearch) {
      filtered = filtered.filter(agent => {
        return agent.name.toLowerCase().includes(currentSwarmSearch) ||
               agent.description.toLowerCase().includes(currentSwarmSearch) ||
               agent.capabilities.some(cap => cap.toLowerCase().includes(currentSwarmSearch));
      });
    }
    
    // 2. Category tag filter
    if (currentSwarmFilter !== 'all') {
      filtered = filtered.filter(agent => {
        const nameLower = agent.name.toLowerCase();
        if (currentSwarmFilter === 'system') {
          return ['supervisor', 'planning', 'coordinator', 'memory', 'verification', 'recovery', 'interaction'].some(n => nameLower.includes(n));
        } else if (currentSwarmFilter === 'coding') {
          return ['coding', 'debugging', 'integration'].some(n => nameLower.includes(n));
        } else if (currentSwarmFilter === 'media') {
          return ['browser', 'vision', 'language'].some(n => nameLower.includes(n));
        }
        return true;
      });
    }
    
    if (filtered.length === 0) {
      swarmAgentsContainer.innerHTML = '<div class="no-data-msg">No nodes matching criteria.</div>';
      return;
    }
    
    swarmAgentsContainer.innerHTML = filtered.map(agent => {
      const capabilitiesHtml = agent.capabilities.map(cap => `<span class="cap-tag">${cap}</span>`).join('');
      const statusClass = `status-${agent.status || 'offline'}`;
      const cleanName = agent.name.replace('Agent', '');
      
      return `
        <div class="agent-card ${statusClass} js-open-inspector" data-inspector-type="agent" data-agent-name="${agent.name}">
          <div class="agent-card-header">
            <div class="agent-card-title">
              <div class="agent-avatar">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                  <circle cx="12" cy="7" r="4"></circle>
                </svg>
              </div>
              <span class="agent-name">${cleanName}</span>
            </div>
            <span class="agent-status-badge">
              <div class="indicator-dot"></div>
              <span>${agent.status || 'offline'}</span>
            </span>
          </div>
          
          <p class="agent-desc">${agent.description}</p>
          
          <div class="agent-capabilities-section">
            <span class="agent-cap-title">Registered Actions</span>
            <div class="capabilities-list">
              ${capabilitiesHtml || '<span class="cap-tag">speak</span>'}
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  // --- Workflows & Schedules Actions ---
  function renderBuilderSteps() {
    if (workflowSteps.length === 0) {
      builderStepsList.innerHTML = '<div class="no-steps-placeholder">No steps defined. Use the builder above.</div>';
      wfStepsInput.value = '';
      return;
    }
    
    builderStepsList.innerHTML = workflowSteps.map((step, idx) => {
      return `
        <div class="builder-step-node">
          <div class="step-node-info">
            <span class="step-node-title">${idx + 1}. ${step.name}</span>
            <span class="step-node-details">${step.agent.replace('_agent', '')} &rarr; ${step.action}</span>
          </div>
          <button type="button" class="btn-remove-step" data-index="${idx}">Remove</button>
        </div>
      `;
    }).join('');
    
    // Bind remove button handlers
    builderStepsList.querySelectorAll('.btn-remove-step').forEach(btn => {
      btn.addEventListener('click', () => {
        const index = parseInt(btn.getAttribute('data-index'), 10);
        workflowSteps.splice(index, 1);
        renderBuilderSteps();
      });
    });
    
    // Sync JSON representation to hidden textarea
    wfStepsInput.value = JSON.stringify(workflowSteps, null, 2);
  }

  // --- Approvals API Actions ---
  function renderApprovalsList(approvals) {
    if (!approvals || approvals.length === 0) {
      approvalsListContainer.innerHTML = '<div class="no-data-msg">Telemetry secure. Swarm agents executing autonomously.</div>';
      syncApprovalsBadge(0, true);
      pillPendingApprovals.classList.add('hidden');
      return;
    }
    
    syncApprovalsBadge(approvals.length, false);
    
    valPillApprovals.textContent = approvals.length;
    pillPendingApprovals.classList.remove('hidden');
    
    approvalsListContainer.innerHTML = approvals.map(app => {
      const detailsStr = typeof app.details === 'object' 
        ? JSON.stringify(app.details, null, 2) 
        : app.details || app.message || '';
        
      return `
        <div class="approval-card">
          <div class="approval-card-header">
            <span class="approval-lbl">Authorization Request</span>
            <span class="badge-tag priority-high">High Risk</span>
          </div>
          
          <p class="description">Command action: <strong>${app.action || 'system call'}</strong></p>
          <pre class="approval-desc">${detailsStr}</pre>
          
          <div class="approval-actions">
            <button class="btn-approve" data-id="${app.id}">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="icon-btn-check"><polyline points="20 6 9 17 4 12"></polyline></svg>
              <span>Approve</span>
            </button>
            <button class="btn-deny" data-id="${app.id}">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="icon-btn-close"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
              <span>Deny</span>
            </button>
          </div>
        </div>
      `;
    }).join('');
    
    // Bind approval click actions
    approvalsListContainer.querySelectorAll('.btn-approve').forEach(btn => {
      btn.addEventListener('click', () => resolveApproval(btn.getAttribute('data-id'), true));
    });
    approvalsListContainer.querySelectorAll('.btn-deny').forEach(btn => {
      btn.addEventListener('click', () => resolveApproval(btn.getAttribute('data-id'), false));
    });
  }

  // --- Observability Data Loading ---
  function renderNotifications(notifications) {
    if (!notifications || notifications.length === 0) {
      notificationsListContainer.innerHTML = '<div class="no-data-msg">No recent notifications logged.</div>';
      return;
    }
    
    // Sort newest first
    const sorted = [...notifications].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

    notificationsListContainer.innerHTML = sorted.map(n => {
      const timeStr = n.timestamp ? new Date(n.timestamp).toLocaleTimeString() : '—';
      const statusClass = n.success ? 'status-success' : 'status-error';
      const notifType = n.type || 'webhook';
      
      return `
        <div class="notif-card ${statusClass}">
          <div class="notif-card-header">
            <div class="notif-title-area">
              <div class="notif-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
                  <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
                </svg>
              </div>
              <span class="notif-title">${n.title || 'System Notification'}</span>
            </div>
            <span class="notif-time">${timeStr}</span>
          </div>
          <p class="notif-message">${n.message || ''}</p>
          <div class="notif-meta-tags">
            <span class="notif-meta-tag">${notifType}</span>
            <span class="notif-meta-tag">${n.success ? 'delivered' : 'failed'}</span>
          </div>
        </div>
      `;
    }).join('');
  }

