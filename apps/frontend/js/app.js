/**
 * JARVIS Neural Control Center - Core Application Logic
 * Integrates LiveKit WebRTC (voice), FastAPI (endpoints, WebSocket telemetry),
 * custom visual workflow builder, and interactive canvas wave animations.
 */

document.addEventListener('DOMContentLoaded', () => {
  // DOM Screens
  window.loginScreen = document.getElementById('login-screen');
  window.dashboardScreen = document.getElementById('dashboard-screen');
  
  // Login Elements
  window.btnConnect = document.getElementById('btn-connect');
  window.apiKeyInput = document.getElementById('api-key-input');
  window.loginError = document.getElementById('login-error');
  
  // Global Header Elements
  window.statusDot = document.getElementById('status-dot');
  window.statusText = document.getElementById('status-text');
  window.btnLogout = document.getElementById('btn-logout-action');
  window.currentTabTitle = document.getElementById('current-tab-title');
  
  // Voice Orb Tab Elements
  window.voiceOrb = document.getElementById('voice-orb');
  window.agentStateText = document.getElementById('agent-state-text');
  window.transcriptBox = document.getElementById('transcript-box');
  window.btnMic = document.getElementById('btn-mic');
  window.iconMicOn = document.querySelector('.icon-mic-on');
  window.iconMicOff = document.querySelector('.icon-mic-off');
  window.btnHangup = document.getElementById('btn-hangup');
  window.remoteAudio = document.getElementById('remote-audio');
  window.btnToggleMode = document.getElementById('btn-toggle-mode');
  window.chatInputContainer = document.querySelector('.chat-input-container');
  window.chatInput = document.getElementById('chat-input');
  window.btnSendChat = document.getElementById('btn-send-chat');
  window.iconKeyboard = document.querySelector('.icon-keyboard');
  window.iconMicToggle = document.querySelector('.icon-mic-toggle');
  window.thinkingBox = document.getElementById('thinking-box');
  window.voiceTabs = document.querySelectorAll('.voice-tab');
  window.voiceTabContents = document.querySelectorAll('.voice-tab-content');
  window.speechTelemetryVal = document.querySelector('#speech-telemetry .val');
  
  // Tasks Tab Elements
  window.taskCommandInput = document.getElementById('task-command-input');
  window.btnSubmitTask = document.getElementById('btn-submit-task');
  window.btnRefreshTasks = document.getElementById('btn-refresh-tasks');
  window.badgeTasksCount = document.getElementById('badge-tasks-count');
  
  // File Uploader Elements
  window.btnAttachFile = document.getElementById('btn-attach-file');
  window.fileUploader = document.getElementById('file-uploader');
  window.attachmentPreview = document.getElementById('attachment-preview');
  window.attachedFileName = document.getElementById('attached-file-name');
  window.btnRemoveAttachment = document.getElementById('btn-remove-attachment');
  
  // Voice Console Chat Uploader Elements
  window.btnChatAttachFile = document.getElementById('btn-chat-attach-file');
  window.chatFileUploader = document.getElementById('chat-file-uploader');
  window.chatAttachmentPreview = document.getElementById('chat-attachment-preview');
  window.chatAttachedFileName = document.getElementById('chat-attached-file-name');
  window.btnChatRemoveAttachment = document.getElementById('btn-chat-remove-attachment');
  
  // Voice Control Dock Uploader Elements
  window.btnVoiceUpload = document.getElementById('btn-voice-upload');
  window.voiceFileUploader = document.getElementById('voice-file-uploader');
  window.voiceAttachmentPreview = document.getElementById('voice-attachment-preview');
  window.voiceAttachedFileName = document.getElementById('voice-attached-file-name');
  window.btnVoiceRemoveAttachment = document.getElementById('btn-voice-remove-attachment');
  
  // Swarm Agents Tab
  window.swarmAgentsContainer = document.getElementById('swarm-agents-container');
  
  // Workflows Tab
  window.workflowCreatorForm = document.getElementById('workflow-creator-form');
  window.scheduleCreatorForm = document.getElementById('schedule-creator-form');
  window.workflowsListContainer = document.getElementById('workflows-list-container');
  window.schedulesListContainer = document.getElementById('schedules-list-container');
  window.wfNameInput = document.getElementById('wf-name');
  window.wfStepsInput = document.getElementById('wf-steps');
  window.schedNameInput = document.getElementById('sched-name');
  window.schedCronInput = document.getElementById('sched-cron');
  window.cronPreviewText = document.getElementById('cron-preview-text');
  window.schedWfSelect = document.getElementById('sched-wf-id');
  
  // Approvals Tab
  window.approvalsListContainer = document.getElementById('approvals-list-container');
  window.badgeApprovalsCount = document.getElementById('badge-approvals-count');
  
  // Observability Tab Metrics
  window.valTotalTasks = document.getElementById('val-total-tasks');
  window.valSuccessRate = document.getElementById('val-success-rate');
  window.valAvgDuration = document.getElementById('val-avg-duration');
  window.valTotalTokens = document.getElementById('val-total-tokens');
  window.valTotalCost = document.getElementById('val-total-cost');
  window.valAvgConfidence = document.getElementById('val-avg-confidence');
  
  // Observability Tables
  window.agentPerformanceTbody = document.getElementById('agent-performance-tbody');
  window.traceSpansTbody = document.getElementById('trace-spans-tbody');
  window.btnRefreshSpans = document.getElementById('btn-refresh-spans');
  
  // New Notifications Tab Elements
  window.notificationsListContainer = document.getElementById('notifications-list-container');
  window.badgeNotificationsCount = document.getElementById('badge-notifications-count');

  // Skills Tab Elements
  window.skillsListContainer = document.getElementById('skills-list-container');
  window.skillMdUploadZone = document.getElementById('skill-md-upload-zone');
  window.skillMdFileInput = document.getElementById('skill-md-file-input');
  window.skillMdPreviewPanel = document.getElementById('skill-md-preview-panel');
  window.skillMdPreviewName = document.getElementById('skill-md-preview-name');
  window.skillMdPreviewDesc = document.getElementById('skill-md-preview-desc');
  window.skillMdPreviewCategory = document.getElementById('skill-md-preview-category');
  window.skillMdPreviewTriggers = document.getElementById('skill-md-preview-triggers');
  window.skillMdErrorMsg = document.getElementById('skill-md-error-msg');
  window.btnDeployMdSkill = document.getElementById('btn-deploy-md-skill');
  
  // Workflow MD Import Elements (moved to dedicated Workflows Library tab)
  window.workflowMdUploadZone = document.getElementById('workflow-library-md-upload-zone');
  window.workflowMdFileInput = document.getElementById('workflow-library-md-file-input');
  window.workflowMdPreviewPanel = document.getElementById('workflow-library-md-preview-panel');
  window.wfMdPreviewName = document.getElementById('workflow-library-md-preview-name');
  window.wfMdPreviewDesc = document.getElementById('workflow-library-md-preview-desc');
  window.wfMdPreviewSchedule = document.getElementById('workflow-library-md-preview-schedule');
  window.wfMdPreviewStepsBody = document.getElementById('workflow-library-md-preview-steps-body');
  window.workflowMdErrorMsg = document.getElementById('workflow-library-md-error-msg');
  window.btnDeployMdWorkflow = document.getElementById('btn-deploy-library-md-workflow');
  window.workflowsLibraryListContainer = document.getElementById('workflows-library-list-container');

  window.currentUploadedSkillMd = "";
  window.currentUploadedWorkflowMd = "";

  // Mobile Nav Elements
  window.mobileNavItems = document.querySelectorAll('.mobile-nav-item');
  window.sheetMenuItems = document.querySelectorAll('.sheet-menu-item');
  window.btnMobileMore = document.getElementById('btn-mobile-more');
  window.mobileMoreSheet = document.getElementById('mobile-more-sheet');
  window.mobileOverlayBackdrop = document.getElementById('mobile-overlay-backdrop');
  window.btnMobileLogout = document.getElementById('btn-mobile-logout');

  window.mobileBadgeTasksCount = document.getElementById('mobile-badge-tasks-count');
  window.mobileBadgeApprovalsCount = document.getElementById('mobile-badge-approvals-count');
  window.mobileBadgeNotificationsCount = document.getElementById('mobile-badge-notifications-count');


  // --- Global Command Palette Search & Indexing ---
  function navigateToTab(tabId) {
    const navItem = document.querySelector(`.nav-item[data-tab="${tabId}"]`);
    if (navItem) {
      navItem.click();
    }
  }

  function buildSearchIndex() {
    searchIndex = [];
    
    // 1. Swarm Directory Agents
    cachedSwarmAgents.forEach(agent => {
      searchIndex.push({
        name: agent.name,
        meta: agent.description,
        type: 'agent',
        badge: 'Swarm Node',
        action: () => {
          navigateToTab('swarm');
          const swarmSearchInput = document.getElementById('swarm-agent-search');
          if (swarmSearchInput) {
            swarmSearchInput.value = agent.name;
            currentSwarmSearch = agent.name.toLowerCase();
            renderSwarmAgentsFiltered();
          }
        }
      });
    });

    // 2. Workflow templates
    const wfItems = workflowsListContainer.querySelectorAll('.wf-item');
    wfItems.forEach(item => {
      const h4 = item.querySelector('h4');
      const name = h4 ? h4.textContent : 'Workflow Target';
      searchIndex.push({
        name: name,
        meta: `Execute or edit workflow template`,
        type: 'workflow',
        badge: 'Workflow',
        action: () => {
          navigateToTab('workflows');
        }
      });
    });

    // 3. Pending approvals
    const approvalCards = approvalsListContainer.querySelectorAll('.approval-card');
    approvalCards.forEach(card => {
      const desc = card.querySelector('.description');
      const text = desc ? desc.textContent : 'high risk gateway confirmation';
      searchIndex.push({
        name: `Approve: ${text}`,
        meta: `Pending gateway security gating`,
        type: 'approval',
        badge: 'Gate Approval',
        action: () => {
          navigateToTab('approvals');
        }
      });
    });

    // 4. Default command shortcuts
    searchIndex.push({
      name: 'Establish Voice Session',
      meta: 'Start real-time voice command stream',
      type: 'command',
      badge: 'System Call',
      action: () => {
        navigateToTab('voice');
        if (!room || room.state !== 'connected') {
          btnConnect.click();
        }
      }
    });
    
    searchIndex.push({
      name: 'Toggle Text Terminal Mode',
      meta: 'Switch Voice Console to keyboard input',
      type: 'command',
      badge: 'UI Mode',
      action: () => {
        navigateToTab('voice');
        if (!isTextMode) {
          toggleMode();
        }
      }
    });

    searchIndex.push({
      name: 'Clear Observability Traces',
      meta: 'Refresh span traces table',
      type: 'command',
      badge: 'Telemetry',
      action: () => {
        navigateToTab('observability');
        btnRefreshSpans.click();
      }
    });
  }

  function openCommandPalette() {
    buildSearchIndex();
    commandPalette.classList.remove('hidden');
    commandPaletteInput.value = '';
    commandPaletteInput.focus();
    renderPaletteResults('');
  }

  function closeCommandPalette() {
    commandPalette.classList.add('hidden');
  }

  function renderPaletteResults(query) {
    const filtered = searchIndex.filter(item => 
      item.name.toLowerCase().includes(query) || 
      item.meta.toLowerCase().includes(query) ||
      item.badge.toLowerCase().includes(query)
    );

    if (filtered.length === 0) {
      commandPaletteResults.innerHTML = '<div class="palette-empty">No matching actions or telemetry found.</div>';
      return;
    }

    commandPaletteResults.innerHTML = filtered.map((item, idx) => {
      let iconSvg = '';
      if (item.type === 'agent') iconSvg = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>';
      else if (item.type === 'workflow') iconSvg = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>';
      else if (item.type === 'approval') iconSvg = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>';
      else iconSvg = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="9" y1="9" x2="15" y2="15"></line><line x1="15" y1="9" x2="9" y2="15"></line></svg>';

      return `
        <div class="palette-item" data-index="${idx}">
          <div class="palette-item-left">
            <div class="palette-item-icon">${iconSvg}</div>
            <div class="palette-item-text">
              <span class="palette-item-name">${item.name}</span>
              <span class="palette-item-meta">${item.meta}</span>
            </div>
          </div>
          <span class="palette-item-badge">${item.badge}</span>
        </div>
      `;
    }).join('');

    // Bind click handlers
    commandPaletteResults.querySelectorAll('.palette-item').forEach(el => {
      el.addEventListener('click', () => {
        const index = parseInt(el.getAttribute('data-index'), 10);
        filtered[index].action();
        closeCommandPalette();
      });
    });
  }

  // --- Session Lifecycle: Connect / Disconnect ---
  async function disconnect() {
    if (isDisconnecting) return;
    isDisconnecting = true;
    
    // Clear pollers
    if (statusPollInterval) clearInterval(statusPollInterval);
    statusPollInterval = null;
    
    try {
      if (room) {
        await room.disconnect();
        room = null;
      }
      if (tasksSocket) {
        tasksSocket.close();
        tasksSocket = null;
      }
      
      jwtToken = null;
      sessionStorage.removeItem('jarvis_jwt_token');
      localStorage.removeItem('jarvis_jwt_token');
      
      dashboardScreen.classList.add('hidden');
      loginScreen.classList.remove('hidden');
      setTimeout(() => {
        loginScreen.classList.add('active');
      }, 50);
      
      updateConnectionStatus('disconnected');
      
      // Reset Text Mode
      isTextMode = false;
      if (btnToggleMode) {
        btnToggleMode.classList.remove('active');
        iconKeyboard.classList.remove('hidden');
        iconMicToggle.classList.add('hidden');
      }
      if (chatInputContainer) chatInputContainer.classList.add('hidden');
      if (chatInput) chatInput.value = '';
      
      // Reset voice tab chat
      transcriptBox.innerHTML = '';
      addChatMessage('system-msg', 'Core system ready. Establishing visual telemetry...');
    } finally {
      isDisconnecting = false;
    }
  }

  async function pollTelemetryBackground() {
    if (!jwtToken) return;
    
    // Load Approvals (updates badge and header pill)
    await loadApprovals();
    
    // Check notifications for unread updates
    try {
      const res = await fetch(`${apiBase}/api/notifications`, {
        headers: getHeaders()
      });
      if (res.ok) {
        const data = await res.json();
        const activeTab = document.querySelector('.nav-item.active').getAttribute('data-tab');
        if (activeTab !== 'notifications' && data.notifications.length > 0) {
          const oldLen = parseInt(localStorage.getItem('jarvis_notif_len') || '0', 10);
          if (data.notifications.length > oldLen) {
            unreadNotificationsCount += (data.notifications.length - oldLen);
            syncNotificationsBadge(unreadNotificationsCount, false);
          }
          localStorage.setItem('jarvis_notif_len', data.notifications.length);
        }
      }
    } catch (e) {
      console.warn("Poll notifications failed:", e);
    }
  }

  // --- Button & Form Event Listeners ---
  // --- Card Switch Event Listeners ---
  const linkGotoSignup = document.getElementById('link-goto-signup');
  const linkGotoLogin = document.getElementById('link-goto-login');
  const cardLogin = document.getElementById('card-login');
  const cardSignup = document.getElementById('card-signup');

  if (linkGotoSignup && linkGotoLogin) {
    linkGotoSignup.addEventListener('click', (e) => {
      e.preventDefault();
      cardLogin.classList.add('hidden');
      cardSignup.classList.remove('hidden');
    });
    linkGotoLogin.addEventListener('click', (e) => {
      e.preventDefault();
      cardSignup.classList.add('hidden');
      cardLogin.classList.remove('hidden');
    });
  }

  btnConnect.addEventListener('click', async () => {
    const loginUserEl = document.getElementById('login-username');
    const loginPassEl = document.getElementById('login-password');
    const username = loginUserEl ? loginUserEl.value.trim() : '';
    const password = loginPassEl ? loginPassEl.value.trim() : '';
    
    let apiKey = apiKeyInput ? apiKeyInput.value.trim() : '';
    
    if (loginError) loginError.classList.add('hidden');
    if (btnConnect) {
      btnConnect.disabled = true;
      const spanEl = btnConnect.querySelector('span');
      if (spanEl) spanEl.textContent = 'CONNECTING...';
    }

    let connectionToken = null;

    if (username && password) {
      // 1. Try logging in with Username/Password
      try {
        const loginRes = await fetch(`${apiBase}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password })
        });
        if (loginRes.ok) {
          const loginData = await loginRes.json();
          connectionToken = loginData.token;
          apiKey = connectionToken;
          sessionStorage.setItem('jarvis_username', username);
          sessionStorage.setItem('jarvis_jwt_token', connectionToken);
          localStorage.removeItem('jarvis_api_key'); // Scrub legacy insecure persistence
        } else {
          const errData = await loginRes.json();
          showError(errData.detail || 'Invalid username or password.');
          if (btnConnect) {
            btnConnect.disabled = false;
            const spanEl = btnConnect.querySelector('span');
            if (spanEl) spanEl.textContent = 'Establish Connection';
          }
          return;
        }
      } catch (err) {
        showError('Authentication service unreachable.');
        if (btnConnect) {
          btnConnect.disabled = false;
          const spanEl = btnConnect.querySelector('span');
          if (spanEl) spanEl.textContent = 'Establish Connection';
        }
        return;
      }
    } else {
      // API key connection (session-scoped)
      if (!apiKey) {
        showError('Please enter secure credentials (username/password or system API key).');
        if (btnConnect) {
          btnConnect.disabled = false;
          const spanEl = btnConnect.querySelector('span');
          if (spanEl) spanEl.textContent = 'Establish Connection';
        }
        return;
      }
      sessionStorage.setItem('jarvis_jwt_token', apiKey);
      localStorage.removeItem('jarvis_api_key');
    }
    
    // 2. Authenticate with FastAPI server on port 8000
    const authOk = await authenticateFastAPI(apiKey);
    if (!authOk) {
      if (btnConnect) {
        btnConnect.disabled = false;
        const spanEl = btnConnect.querySelector('span');
        if (spanEl) spanEl.textContent = 'Establish Connection';
      }
      return;
    }
    
    // 3. Connect LiveKit Voice stream on port 8000
    await connectToLiveKit(apiKey);
    
    // 4. Setup polling and WebSockets once authenticated
    if (jwtToken) {
      connectTasksWebSocket();
      
      // Load initial layout info
      loadApprovals();
      
      // Fetch user profile data
      loadUserProfile();
      
      // Poll approvals & notifications periodically
      statusPollInterval = setInterval(pollTelemetryBackground, 15000);
    }
  });

  btnMic.addEventListener('click', toggleMute);
  btnToggleMode.addEventListener('click', toggleMode);
  btnSendChat.addEventListener('click', sendChatMessage);
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendChatMessage();
  });
  btnHangup.addEventListener('click', disconnect);
  btnLogout.addEventListener('click', disconnect);
  
  // Submit NL Tasks command
  if (btnSubmitTask && taskCommandInput) {
    btnSubmitTask.addEventListener('click', submitTaskCommand);
    taskCommandInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') submitTaskCommand();
    });
  }
  if (btnRefreshTasks) {
    btnRefreshTasks.addEventListener('click', loadTasks);
  }
  
  // File Uploader Event Bindings
  if (btnAttachFile && fileUploader) {
    btnAttachFile.addEventListener('click', () => {
      fileUploader.click();
    });
    
    fileUploader.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (!file) return;
      
      selectedFile = file;
      attachedFileName.textContent = file.name;
      attachmentPreview.classList.remove('hidden');
    });
  }
  
  if (btnRemoveAttachment) {
    btnRemoveAttachment.addEventListener('click', () => {
      selectedFile = null;
      fileUploader.value = '';
      attachmentPreview.classList.add('hidden');
    });
  }
  
  // Chat File Uploader Event Bindings
  if (btnChatAttachFile && chatFileUploader) {
    btnChatAttachFile.addEventListener('click', () => {
      chatFileUploader.click();
    });
    
    chatFileUploader.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (!file) return;
      
      chatSelectedFile = file;
      chatAttachedFileName.textContent = file.name;
      chatAttachmentPreview.classList.remove('hidden');
    });
  }
  
  if (btnChatRemoveAttachment) {
    btnChatRemoveAttachment.addEventListener('click', () => {
      chatSelectedFile = null;
      chatFileUploader.value = '';
      chatAttachmentPreview.classList.add('hidden');
    });
  }
  
  // Voice Dock File Uploader Event Bindings
  if (btnVoiceUpload && voiceFileUploader) {
    btnVoiceUpload.addEventListener('click', () => {
      voiceFileUploader.click();
    });
    
    btnVoiceUpload.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      
      voiceSelectedFile = file;
      voiceAttachedFileName.textContent = file.name;
      voiceAttachmentPreview.classList.remove('hidden');
      
      // Upload immediately for voice session context
      try {
        addChatMessage('system-msg', `Uploading voice attachment: ${file.name}...`);
        const base64Content = await readFileAsBase64(file);
        const uploadRes = await fetch(`${apiBase}/api/upload`, {
          method: 'POST',
          headers: getHeaders(),
          body: JSON.stringify({
            filename: file.name,
            content: base64Content
          })
        });
        
        if (!uploadRes.ok) {
          const errData = await uploadRes.json();
          throw new Error(errData.detail || 'File upload failed.');
        }
        
        const uploadData = await uploadRes.json();
        const filepath = uploadData.filepath;
        
        // Register context with LiveKit if connected
        if (room && room.state === 'connected') {
          const encoder = new TextEncoder();
          const payload = JSON.stringify({
            type: 'user_chat',
            text: `[System Event: File Context Attached] User uploaded file to workspace: "${filepath}"`
          });
          const data = encoder.encode(payload);
          await room.localParticipant.publishData(data, { reliable: true });
          addChatMessage('system-msg', `Attachment registered with active voice session: ${file.name}`);
        } else {
          addChatMessage('system-msg', `File uploaded: ${file.name}. Connect voice to synchronize context.`);
        }
      } catch (err) {
        console.error('Voice file upload failed:', err);
        addChatMessage('system-msg', `Failed to upload voice attachment: ${err.message}`);
      }
    });
  }
  
  if (btnVoiceRemoveAttachment) {
    btnVoiceRemoveAttachment.addEventListener('click', () => {
      voiceSelectedFile = null;
      voiceFileUploader.value = '';
      voiceAttachmentPreview.classList.add('hidden');
    });
  }
  
  // Workflow creation/triggers
  workflowCreatorForm.addEventListener('submit', createWorkflow);
  scheduleCreatorForm.addEventListener('submit', createSchedule);

  // Skills Tab drag-and-drop / file upload setup
  if (skillMdUploadZone && skillMdFileInput) {
    setupDragDropZone(skillMdUploadZone, skillMdFileInput, handleCustomSkillFile);
  }
  
  if (btnDeployMdSkill) {
    btnDeployMdSkill.addEventListener('click', async () => {
      if (!currentUploadedSkillMd) return;
      
      btnDeployMdSkill.setAttribute('disabled', 'true');
      const originalText = btnDeployMdSkill.textContent;
      btnDeployMdSkill.textContent = "DEPLOYING...";
      
      try {
        const depRes = await fetch(`${apiBase}/api/skills`, {
          method: 'POST',
          headers: getHeaders(),
          body: JSON.stringify({ raw_markdown: currentUploadedSkillMd })
        });
        if (!depRes.ok) {
          const errData = await depRes.json();
          throw new Error(errData.detail || 'Deploy failed.');
        }
        
        alert("Custom skill deployed successfully!");
        skillMdPreviewPanel.classList.add('hidden');
        currentUploadedSkillMd = "";
        skillMdFileInput.value = "";
        loadSkills();
      } catch (err) {
        alert("Failed to deploy skill: " + err.message);
      } finally {
        btnDeployMdSkill.removeAttribute('disabled');
        btnDeployMdSkill.textContent = originalText;
      }
    });
  }

  // Workflows MD Import drag-and-drop / file upload setup
  if (workflowMdUploadZone && workflowMdFileInput) {
    setupDragDropZone(workflowMdUploadZone, workflowMdFileInput, handleWorkflowMdFile);
  }

  if (btnDeployMdWorkflow) {
    btnDeployMdWorkflow.addEventListener('click', async () => {
      if (!currentUploadedWorkflowMd) return;
      
      btnDeployMdWorkflow.setAttribute('disabled', 'true');
      const originalText = btnDeployMdWorkflow.textContent;
      btnDeployMdWorkflow.textContent = "DEPLOYING...";
      
      try {
        const depRes = await fetch(`${apiBase}/api/workflows/import-md`, {
          method: 'POST',
          headers: getHeaders(),
          body: JSON.stringify({ raw_markdown: currentUploadedWorkflowMd })
        });
        if (!depRes.ok) {
          const errData = await depRes.json();
          throw new Error(errData.detail || 'Deploy failed.');
        }
        
        alert("Workflow imported from markdown successfully!");
        workflowMdPreviewPanel.classList.add('hidden');
        currentUploadedWorkflowMd = "";
        workflowMdFileInput.value = "";
        loadWorkflowsAndSchedules();
      } catch (err) {
        alert("Failed to deploy workflow: " + err.message);
      } finally {
        btnDeployMdWorkflow.removeAttribute('disabled');
        btnDeployMdWorkflow.textContent = originalText;
      }
    });
  }
  
  // Observability refresh
  btnRefreshSpans.addEventListener('click', loadTraceSpans);
  
  // Swarm Directory Filters Bindings
  const filterTags = document.querySelectorAll('.filter-tag');
  filterTags.forEach(tag => {
    tag.addEventListener('click', () => {
      filterTags.forEach(t => t.classList.remove('active'));
      tag.classList.add('active');
      currentSwarmFilter = tag.getAttribute('data-type');
      renderSwarmAgentsFiltered();
    });
  });

  const swarmSearchInput = document.getElementById('swarm-agent-search');
  if (swarmSearchInput) {
    swarmSearchInput.addEventListener('input', (e) => {
      currentSwarmSearch = e.target.value.toLowerCase().trim();
      renderSwarmAgentsFiltered();
    });
  }

  // Voice tab panels navigation
  voiceTabs.forEach(tabBtn => {
    tabBtn.addEventListener('click', () => {
      voiceTabs.forEach(b => b.classList.remove('active'));
      tabBtn.classList.add('active');
      
      const tabName = tabBtn.getAttribute('data-voice-tab');
      voiceTabContents.forEach(content => {
        content.classList.remove('active');
        if (content.id === `voice-tab-${tabName}`) {
          content.classList.add('active');
        }
      });
    });
  });

  // Cron schedule helper translator
  if (schedCronInput) {
    schedCronInput.addEventListener('input', (e) => {
      cronPreviewText.textContent = translateCron(e.target.value);
    });
  }

  // Global Command Palette events
  btnCommandTrigger.addEventListener('click', openCommandPalette);
  
  commandPalette.addEventListener('click', (e) => {
    if (e.target === commandPalette) closeCommandPalette();
  });

  commandPaletteInput.addEventListener('input', (e) => {
    renderPaletteResults(e.target.value.toLowerCase().trim());
  });

  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      openCommandPalette();
    }
    if (e.key === 'Escape') {
      closeCommandPalette();
    }
  });

  // --- Precision Audio Spectrum & Oscilloscope Wave visualizer ---
  const canvas = document.getElementById('wave-canvas');
  if (canvas) {
    const ctx = canvas.getContext('2d');
    let phase = 0;
    
    function drawWaves() {
      if (!canvas.offsetParent) {
        requestAnimationFrame(drawWaves);
        return;
      }
      
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);
      
      ctx.clearRect(0, 0, rect.width, rect.height);
      
      let speed = 0.04;
      let amplitude = 8;
      let waveCount = 2;
      let colors = ['rgba(59, 130, 246, 0.4)', 'rgba(255, 255, 255, 0.08)'];
      
      // Get real audio volume if active
      const liveVolume = getActiveAmplitude();
      
      if (currentOrbState === 'speaking') {
        speed = 0.12 + (liveVolume * 0.06);
        amplitude = 15 + (liveVolume * 40);
        waveCount = 4;
        colors = [
          'rgba(59, 130, 246, 0.85)',
          'rgba(14, 165, 233, 0.6)',
          'rgba(16, 185, 129, 0.4)',
          'rgba(59, 130, 246, 0.2)'
        ];
      } else if (currentOrbState === 'listening') {
        speed = 0.14 + (liveVolume * 0.08);
        amplitude = 12 + (liveVolume * 45);
        waveCount = 3;
        colors = [
          'rgba(16, 185, 129, 0.85)',
          'rgba(14, 165, 233, 0.5)',
          'rgba(16, 185, 129, 0.25)'
        ];
      } else if (currentOrbState === 'thinking') {
        speed = 0.06;
        amplitude = 10 + Math.sin(Date.now() * 0.003) * 6;
        waveCount = 3;
        colors = [
          'rgba(139, 92, 246, 0.65)',
          'rgba(59, 130, 246, 0.4)',
          'rgba(255, 255, 255, 0.1)'
        ];
      } else if (currentOrbState === 'text-mode') {
        speed = 0.02;
        amplitude = 5;
        waveCount = 1;
        colors = ['rgba(59, 130, 246, 0.3)'];
      }
      
      phase += speed;
      const width = rect.width;
      const height = rect.height;
      const centerY = height / 2;

      // Render vertical audio frequency bars in background if active
      if (currentOrbState === 'speaking' || currentOrbState === 'listening') {
        const barCount = 18;
        const barWidth = 3;
        const spacing = (width * 0.7) / barCount;
        const startX = (width - (barCount * spacing)) / 2;
        
        for (let b = 0; b < barCount; b++) {
          const barHeight = 4 + (Math.sin(phase * 2 + b * 0.4) + 1) * (12 + liveVolume * 30);
          const x = startX + (b * spacing);
          ctx.fillStyle = colors[0];
          ctx.fillRect(x, centerY - (barHeight / 2), barWidth, barHeight);
        }
      }
      
      for (let i = 0; i < waveCount; i++) {
        ctx.beginPath();
        ctx.strokeStyle = colors[i];
        ctx.lineWidth = i === 0 ? 2.5 : 1.2;
        
        const wavePhase = phase + (i * Math.PI / 3.5);
        const waveScale = 1 - (i * 0.22);
        
        for (let x = 0; x < width; x++) {
          // Attenuated sine wave pinching at edges
          const y = centerY + Math.sin((x * 0.025) + wavePhase) * amplitude * waveScale * Math.sin(x * Math.PI / width);
          if (x === 0) {
            ctx.moveTo(x, y);
          } else {
            ctx.lineTo(x, y);
          }
        }
        ctx.stroke();
      }
      
      requestAnimationFrame(drawWaves);
    }
    
    drawWaves();
  }

  // --- Signup, Profile management, and Test notification helpers ---
  const btnSignupSubmit = document.getElementById('btn-signup-submit');
  const signupError = document.getElementById('signup-error');
  const signupSuccess = document.getElementById('signup-success');
  
  if (btnSignupSubmit) {
    btnSignupSubmit.addEventListener('click', async () => {
      const usernameEl = document.getElementById('signup-username');
      const passwordEl = document.getElementById('signup-password');
      const emailEl = document.getElementById('signup-email');
      const phoneEl = document.getElementById('signup-phone');

      const username = usernameEl ? usernameEl.value.trim() : '';
      const password = passwordEl ? passwordEl.value.trim() : '';
      const email = emailEl ? emailEl.value.trim() : '';
      const phone = phoneEl ? phoneEl.value.trim() : '';
      
      if (!username || !password) {
        if (signupError) {
          signupError.textContent = 'Username and password are required.';
          signupError.classList.remove('hidden');
        }
        return;
      }
      if (password.length < 6) {
        if (signupError) {
          signupError.textContent = 'Password must be at least 6 characters.';
          signupError.classList.remove('hidden');
        }
        return;
      }
      
      if (signupError) signupError.classList.add('hidden');
      if (signupSuccess) signupSuccess.classList.add('hidden');
      btnSignupSubmit.disabled = true;
      
      try {
        const res = await fetch(`${apiBase}/api/auth/signup`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: username,
            password: password,
            email: email,
            phone_number: phone
          })
        });
        
        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || 'Registration failed');
        }
        
        signupSuccess.classList.remove('hidden');
        
        setTimeout(async () => {
          const loginUserEl = document.getElementById('login-username');
          const loginPassEl = document.getElementById('login-password');
          if (loginUserEl) loginUserEl.value = username;
          if (loginPassEl) loginPassEl.value = password;
          
          // Switch to login card
          const cardSignup = document.getElementById('card-signup');
          const cardLogin = document.getElementById('card-login');
          if (cardSignup) cardSignup.classList.add('hidden');
          if (cardLogin) cardLogin.classList.remove('hidden');
          
          if (btnConnect) btnConnect.click();
          btnSignupSubmit.disabled = false;
        }, 1500);
      } catch (err) {
        if (signupError) {
          signupError.textContent = err.message;
          signupError.classList.remove('hidden');
        }
        btnSignupSubmit.disabled = false;
      }
    });
  }

  async function loadUserProfile() {
    try {
      const res = await fetch(`${apiBase}/api/auth/me`, {
        headers: getHeaders()
      });
      if (!res.ok) return;
      const data = await res.json();
      
      const userEl = document.getElementById('profile-username');
      const emailEl = document.getElementById('profile-email');
      const phoneEl = document.getElementById('profile-phone');
      
      if (userEl) userEl.value = data.username || '';
      if (emailEl) emailEl.value = data.email || '';
      if (phoneEl) phoneEl.value = data.phone_number || '';
    } catch (e) {
      console.warn("Failed to load user profile:", e);
    }
  }

  const btnProfileSave = document.getElementById('btn-profile-save');
  const profileError = document.getElementById('profile-error');
  const profileSuccess = document.getElementById('profile-success');

  if (btnProfileSave) {
    btnProfileSave.addEventListener('click', async () => {
      const emailEl = document.getElementById('profile-email');
      const phoneEl = document.getElementById('profile-phone');
      const oldPasswordEl = document.getElementById('profile-old-password');
      const newPasswordEl = document.getElementById('profile-new-password');

      const email = emailEl ? emailEl.value.trim() : '';
      const phone = phoneEl ? phoneEl.value.trim() : '';
      const oldPassword = oldPasswordEl ? oldPasswordEl.value.trim() : '';
      const newPassword = newPasswordEl ? newPasswordEl.value.trim() : '';

      if (profileError) profileError.classList.add('hidden');
      if (profileSuccess) profileSuccess.classList.add('hidden');

      const bodyData = {
        email: email,
        phone_number: phone
      };

      if (newPassword) {
        if (!oldPassword) {
          if (profileError) {
            profileError.textContent = 'Current password is required to change password.';
            profileError.classList.remove('hidden');
          }
          return;
        }
        bodyData.password = newPassword;
        bodyData.old_password = oldPassword;
      }

      try {
        const res = await fetch(`${apiBase}/api/auth/update`, {
          method: 'POST',
          headers: getHeaders(),
          body: JSON.stringify(bodyData)
        });

        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || 'Failed to update profile settings');
        }

        if (profileSuccess) profileSuccess.classList.remove('hidden');
        if (oldPasswordEl) oldPasswordEl.value = '';
        if (newPasswordEl) newPasswordEl.value = '';
        setTimeout(() => {
          if (profileSuccess) profileSuccess.classList.add('hidden');
        }, 3000);
      } catch (err) {
        if (profileError) {
          profileError.textContent = err.message;
          profileError.classList.remove('hidden');
        }
      }
    });
  }

  const btnTestEmail = document.getElementById('btn-test-email');
  const btnTestSms = document.getElementById('btn-test-sms');
  const testNotifError = document.getElementById('test-notif-error');
  const testNotifSuccess = document.getElementById('test-notif-success');

  async function triggerTestNotification(type) {
    testNotifError.classList.add('hidden');
    testNotifSuccess.classList.add('hidden');
    
    try {
      const res = await fetch(`${apiBase}/api/notifications`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          type: type,
          title: "JARVIS Integration Test",
          message: `This is a test ${type.toUpperCase()} notification from your JARVIS Voice Assistant.`
        })
      });
      
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Notification dispatch failed');
      }
      
      testNotifSuccess.textContent = `Test ${type.toUpperCase()} notification triggered successfully!`;
      testNotifSuccess.classList.remove('hidden');
      setTimeout(() => testNotifSuccess.classList.add('hidden'), 4000);
      
      loadNotifications();
    } catch (err) {
      testNotifError.textContent = err.message;
      testNotifError.classList.remove('hidden');
    }
  }

  if (btnTestEmail) btnTestEmail.addEventListener('click', () => triggerTestNotification('email'));
  if (btnTestSms) btnTestSms.addEventListener('click', () => triggerTestNotification('sms'));

  // --- Settings Modal Trigger Logic ---
  const settingsModal = document.getElementById('settings-modal');
  const btnSettingsTrigger = document.getElementById('btn-settings-trigger');
  const btnSettingsClose = document.getElementById('btn-settings-close');
  const btnMobileSettings = document.getElementById('btn-mobile-settings');

  if (btnSettingsTrigger) {
    btnSettingsTrigger.addEventListener('click', () => {
      if (settingsModal) {
        settingsModal.classList.remove('hidden');
        loadUserProfile();
      }
    });
  }

  if (btnMobileSettings) {
    btnMobileSettings.addEventListener('click', () => {
      // Hide mobile sheet if open
      if (mobileMoreSheet) mobileMoreSheet.classList.add('hidden');
      if (mobileOverlayBackdrop) mobileOverlayBackdrop.classList.add('hidden');
      if (settingsModal) {
        settingsModal.classList.remove('hidden');
        loadUserProfile();
      }
    });
  }

  if (btnSettingsClose) {
    btnSettingsClose.addEventListener('click', () => {
      if (settingsModal) {
        settingsModal.classList.add('hidden');
      }
    });
  }

  if (settingsModal) {
    settingsModal.addEventListener('click', (e) => {
      if (e.target === settingsModal) {
        settingsModal.classList.add('hidden');
      }
    });
  }

  // --- Session Persistence: Check for existing session on page load ---
  async function checkExistingSession() {
    const savedToken = sessionStorage.getItem('jarvis_jwt_token') || localStorage.getItem('jarvis_jwt_token');
    if (!savedToken) return;

    if (btnConnect) {
      btnConnect.disabled = true;
      const spanEl = btnConnect.querySelector('span');
      if (spanEl) spanEl.textContent = 'RECONNECTING...';
    }

    try {
      const authOk = await authenticateFastAPI(savedToken);
      if (authOk) {
        await connectToLiveKit(savedToken);
        if (jwtToken) {
          connectTasksWebSocket();
          loadApprovals();
          loadUserProfile();
          if (statusPollInterval) clearInterval(statusPollInterval);
          statusPollInterval = setInterval(pollTelemetryBackground, 15000);
        }
      } else {
        sessionStorage.removeItem('jarvis_jwt_token');
        localStorage.removeItem('jarvis_jwt_token');
      }
    } catch (err) {
      console.warn("Auto session restore note:", err);
    } finally {
      if (btnConnect && (!room || room.state !== 'connected')) {
        btnConnect.disabled = false;
        const spanEl = btnConnect.querySelector('span');
        if (spanEl) spanEl.textContent = 'Establish Connection';
      }
    }
  }

  // Attempt auto-reconnection on startup if authenticated previously
  checkExistingSession();
  
});
