  // ── Global DOM References (Window Scope) ──────────────────────────────────
  window.apiKeyInput = document.getElementById('api-key-input');
  window.loginError = document.getElementById('login-error');
  window.currentTabTitle = document.getElementById('current-tab-title');
  window.mobileNavItems = document.querySelectorAll('.mobile-nav-item');
  window.sheetMenuItems = document.querySelectorAll('.sheet-menu-item');
  window.mobileMoreSheet = document.getElementById('mobile-more-sheet');
  window.mobileOverlayBackdrop = document.getElementById('mobile-overlay-backdrop');
  window.btnMobileMore = document.getElementById('btn-mobile-more');
  window.btnMobileLogout = document.getElementById('btn-mobile-logout');

  window.badgeTasksCount = document.getElementById('badge-tasks-count');
  window.mobileBadgeTasksCount = document.getElementById('mobile-badge-tasks-count');
  window.badgeApprovalsCount = document.getElementById('badge-approvals-count');
  window.mobileBadgeApprovalsCount = document.getElementById('mobile-badge-approvals-count');
  window.badgeNotificationsCount = document.getElementById('badge-notifications-count');
  window.mobileBadgeNotificationsCount = document.getElementById('mobile-badge-notifications-count');

  // Command Palette Elements
  window.commandPalette = document.getElementById('command-palette');
  window.commandPaletteInput = document.getElementById('command-palette-input');
  window.commandPaletteResults = document.getElementById('command-palette-results');
  window.btnCommandTrigger = document.getElementById('btn-command-trigger');

  // Header status pill elements
  window.pillActiveTasks = document.getElementById('pill-active-tasks');
  window.valPillTasks = document.getElementById('val-pill-tasks');
  window.pillPendingApprovals = document.getElementById('pill-pending-approvals');
  window.valPillApprovals = document.getElementById('val-pill-approvals');

  // ── Global State Variables (Window Scope) ────────────────────────────────
  window.room = null;
  window.isMuted = false;
  window.isDisconnecting = false;
  window.jwtToken = null;
  window.tasksSocket = null;
  window.statusPollInterval = null;
  window.isTextMode = false;
  window.currentOrbState = 'idle';
  window.unreadNotificationsCount = 0;
  window.selectedFile = null;
  window.chatSelectedFile = null;
  window.voiceSelectedFile = null;
  
  // Swarm cache & filtering state
  window.cachedSwarmAgents = [];
  window.currentSwarmFilter = 'all';
  window.currentSwarmSearch = '';
  
  // Workflow visual steps cache
  window.workflowSteps = [];

  // Inspector panel lookup caches (populated by tasks.js / api.js render functions)
  window.cachedTasksList = [];
  window.cachedWorkflows = [];

  // Audio Context telemetry variables
  window.audioCtx = null;
  window.remoteAnalyser = null;
  window.localAnalyser = null;
  
  // Global search index
  window.searchIndex = [];

  // ── General Utility Functions ─────────────────────────────────────────────
  function updateBadge(badgeEl, count, isHidden) {
    if (!badgeEl) return;
    if (isHidden) {
      badgeEl.classList.add('hidden');
    } else {
      badgeEl.textContent = count;
      badgeEl.classList.remove('hidden');
    }
  }

  function syncTasksBadge(count, isHidden) {
    updateBadge(window.badgeTasksCount, count, isHidden);
    updateBadge(window.mobileBadgeTasksCount, count, isHidden);
  }

  function syncApprovalsBadge(count, isHidden) {
    updateBadge(window.badgeApprovalsCount, count, isHidden);
    updateBadge(window.mobileBadgeApprovalsCount, count, isHidden);
  }

  function syncNotificationsBadge(count, isHidden) {
    updateBadge(window.badgeNotificationsCount, count, isHidden);
    updateBadge(window.mobileBadgeNotificationsCount, count, isHidden);
  }
  
  // HTML entity escaping helper
  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
  window.escapeHtml = escapeHtml;

  // Dynamic API hosts
  const currentOrigin = window.location.origin;
  const isDevVite = window.location.port === '5173';
  const apiBase = isDevVite 
    ? (window.location.protocol + '//' + window.location.hostname + ':8000') 
    : (currentOrigin && currentOrigin !== 'null' ? currentOrigin : 'http://localhost:8000');
  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsHost = isDevVite ? `${window.location.hostname}:8000` : (window.location.host || 'localhost:8000');
  const wsBase = `${wsProto}//${wsHost}`;
  const flaskBase = apiBase;

  // Scrub legacy insecure persistent API key
  localStorage.removeItem('jarvis_api_key');
  
  // Restore session username
  const savedUsername = sessionStorage.getItem('jarvis_username') || localStorage.getItem('jarvis_username');
  const loginUserField = document.getElementById('login-username');
  if (savedUsername && loginUserField) {
    loginUserField.value = savedUsername;
  }

  // --- General Helpers ---
  function getHeaders() {
    return {
      'Content-Type': 'application/json',
      'Authorization': jwtToken ? `Bearer ${jwtToken}` : ''
    };
  }

  function showError(msg) {
    loginError.textContent = msg;
    loginError.classList.remove('hidden');
  }

  // --- Navigation Tab Logic ---
  const navItems = document.querySelectorAll('.nav-item');
  const tabPanes = document.querySelectorAll('.tab-pane');

  function switchTab(tabId) {
    // 1. Update desktop sidebar active item
    navItems.forEach(nav => {
      if (nav.getAttribute('data-tab') === tabId) {
        nav.classList.add('active');
        // Update Title
        currentTabTitle.textContent = nav.querySelector('span:not(.badge)').textContent;
      } else {
        nav.classList.remove('active');
      }
    });

    // 2. Update mobile bottom nav active item
    mobileNavItems.forEach(nav => {
      if (nav.getAttribute('data-tab') === tabId) {
        nav.classList.add('active');
      } else {
        nav.classList.remove('active');
      }
    });

    // 3. Update active tab panel
    tabPanes.forEach(pane => pane.classList.remove('active'));
    const activePane = document.getElementById(`tab-${tabId}`);
    if (activePane) activePane.classList.add('active');

    // 4. Update Title (fallback in case tab is in sheet menu)
    const matchedSheetItem = Array.from(sheetMenuItems).find(item => item.getAttribute('data-tab') === tabId);
    if (matchedSheetItem) {
      currentTabTitle.textContent = matchedSheetItem.querySelector('span:not(.badge)').textContent;
    }

    // 5. Hide sheet and backdrop if open
    mobileMoreSheet.classList.add('hidden');
    mobileOverlayBackdrop.classList.add('hidden');

    // 6. Trigger Tab-specific Loads
    if (tabId === 'swarm') {
      loadSwarmAgents();
      loadSkills();
    } else if (tabId === 'workflows') {
      loadWorkflowsAndSchedules();
    } else if (tabId === 'approvals') {
      loadApprovals();
    } else if (tabId === 'observability') {
      loadObservabilityData();
      loadNotifications();
      resetNotificationsBadge();
    } else if (tabId === 'tasks') {
      loadTasks();
    }
  }

  navItems.forEach(item => {
    item.addEventListener('click', () => {
      const tabId = item.getAttribute('data-tab');
      switchTab(tabId);
    });
  });

  mobileNavItems.forEach(item => {
    item.addEventListener('click', () => {
      const tabId = item.getAttribute('data-tab');
      if (tabId) {
        switchTab(tabId);
      }
    });
  });

  sheetMenuItems.forEach(item => {
    item.addEventListener('click', () => {
      const tabId = item.getAttribute('data-tab');
      if (tabId) {
        switchTab(tabId);
      }
    });
  });

  btnMobileMore.addEventListener('click', () => {
    mobileMoreSheet.classList.toggle('hidden');
    mobileOverlayBackdrop.classList.toggle('hidden');
  });

  mobileOverlayBackdrop.addEventListener('click', () => {
    mobileMoreSheet.classList.add('hidden');
    mobileOverlayBackdrop.classList.add('hidden');
  });

  btnMobileLogout.addEventListener('click', () => {
    mobileMoreSheet.classList.add('hidden');
    mobileOverlayBackdrop.classList.add('hidden');
    disconnect();
  });

  // --- Voice UI Actions ---
  function showProcessingIndicator() {
    if (document.getElementById('processing-indicator')) return;

    const indicatorDiv = document.createElement('div');
    indicatorDiv.id = 'processing-indicator';
    indicatorDiv.className = 'chat-msg agent processing-indicator';

    const avatarDiv = document.createElement('div');
    avatarDiv.className = 'msg-avatar agent-avatar';
    avatarDiv.innerHTML = `
      <div class="avatar-orb thinking">
        <div class="avatar-ring"></div>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="3" fill="currentColor" fill-opacity="0.2"/>
          <path d="M12 2v2M12 20v2M4 12H2M22 12h-2"/>
        </svg>
      </div>
    `;

    const contentDiv = document.createElement('div');
    contentDiv.className = 'msg-content';
    
    const dotsDiv = document.createElement('div');
    dotsDiv.className = 'processing-pulse-dots';
    dotsDiv.innerHTML = '<span></span><span></span><span></span>';
    
    contentDiv.appendChild(dotsDiv);
    indicatorDiv.appendChild(avatarDiv);
    indicatorDiv.appendChild(contentDiv);
    transcriptBox.appendChild(indicatorDiv);
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
  }

  function removeProcessingIndicator() {
    const indicator = document.getElementById('processing-indicator');
    if (indicator) {
      indicator.remove();
    }
  }

  function addChatMessage(role, text) {
    removeProcessingIndicator();

    const msgDiv = document.createElement('div');
    msgDiv.className = `chat-msg ${role}`;
    
    if (role === 'user') {
      const avatarDiv = document.createElement('div');
      avatarDiv.className = 'msg-avatar user-avatar';
      avatarDiv.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
          <circle cx="12" cy="7" r="4"></circle>
        </svg>
      `;
      msgDiv.appendChild(avatarDiv);
    } else if (role === 'agent') {
      const avatarDiv = document.createElement('div');
      avatarDiv.className = 'msg-avatar agent-avatar';
      avatarDiv.innerHTML = `
        <div class="avatar-orb">
          <div class="avatar-ring"></div>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="12" cy="12" r="4" fill="currentColor" fill-opacity="0.1"/>
            <path d="M12 2v2M12 20v2M4 12H2M22 12h-2M12 7v10M7 12h10"/>
          </svg>
        </div>
      `;
      msgDiv.appendChild(avatarDiv);
    } else if (role === 'system-msg') {
      const systemBadge = document.createElement('div');
      systemBadge.className = 'system-badge';
      systemBadge.textContent = 'SYS';
      msgDiv.appendChild(systemBadge);
    }
    
    const contentWrapper = document.createElement('div');
    contentWrapper.className = 'msg-content-wrapper';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'msg-content';
    
    if (role === 'agent') {
      try {
        const rawHtml = marked.parse(text);
        contentDiv.innerHTML = DOMPurify.sanitize(rawHtml);
        contentDiv.querySelectorAll('pre code').forEach((block) => {
          hljs.highlightElement(block);
        });
      } catch (e) {
        console.error('Error parsing markdown:', e);
        contentDiv.textContent = text;
      }
    } else {
      contentDiv.textContent = text;
    }
    
    contentWrapper.appendChild(contentDiv);
    
    if (role === 'user' || role === 'agent') {
      const metaDiv = document.createElement('div');
      metaDiv.className = 'msg-meta';
      
      const now = new Date();
      const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const timeSpan = document.createElement('span');
      timeSpan.className = 'msg-time';
      timeSpan.textContent = timeStr;
      metaDiv.appendChild(timeSpan);
      
      const actionsDiv = document.createElement('div');
      actionsDiv.className = 'msg-actions';
      
      const copyBtn = document.createElement('button');
      copyBtn.className = 'btn-msg-action btn-copy-msg';
      copyBtn.title = 'Copy message';
      copyBtn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
        </svg>
      `;
      copyBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        navigator.clipboard.writeText(text).then(() => {
          copyBtn.classList.add('copied');
          copyBtn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
          `;
          setTimeout(() => {
            copyBtn.classList.remove('copied');
            copyBtn.innerHTML = `
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
            `;
          }, 2000);
        }).catch(err => console.error('Failed to copy text: ', err));
      });
      
      actionsDiv.appendChild(copyBtn);
      metaDiv.appendChild(actionsDiv);
      contentWrapper.appendChild(metaDiv);
    }
    
    msgDiv.appendChild(contentWrapper);
    transcriptBox.appendChild(msgDiv);
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
  }

  function addReasoningNode(title, content) {
    const node = document.createElement('div');
    node.className = 'thinking-node';
    
    const header = document.createElement('div');
    node.appendChild(header);
    header.className = 'thinking-node-header';
    
    const titleSpan = document.createElement('span');
    titleSpan.className = 'thinking-node-title';
    titleSpan.textContent = title;
    
    const timeSpan = document.createElement('span');
    timeSpan.textContent = new Date().toLocaleTimeString();
    
    header.appendChild(titleSpan);
    header.appendChild(timeSpan);
    
    const body = document.createElement('div');
    body.className = 'thinking-node-body';
    body.textContent = content;
    node.appendChild(body);
    
    thinkingBox.appendChild(node);
    thinkingBox.scrollTop = thinkingBox.scrollHeight;
    
    const placeholder = thinkingBox.querySelector('.no-data-msg');
    if (placeholder) {
      placeholder.remove();
    }
  }

  function updateOrbState(state) {
    voiceOrb.className = `orb-container-body ${state}`;
    currentOrbState = state;
    
    const orbGlow = document.getElementById('orb-glow');
    if (orbGlow) {
      orbGlow.className = `orb-glow-backdrop ${state}`;
    }
    
    if (state === 'speaking') {
      agentStateText.textContent = isTextMode ? 'TYPING...' : 'SPEAKING...';
      agentStateText.className = 'agent-state-text active';
      speechTelemetryVal.textContent = 'AGENT SPEAKING';
    } else if (state === 'listening') {
      agentStateText.textContent = 'LISTENING...';
      agentStateText.className = 'agent-state-text active';
      speechTelemetryVal.textContent = 'USER STREAM ACTIVE';
    } else if (state === 'thinking') {
      agentStateText.textContent = 'THINKING...';
      agentStateText.className = 'agent-state-text active';
      speechTelemetryVal.textContent = 'THINKING BUS';
    } else if (state === 'text-mode') {
      agentStateText.textContent = 'TEXT TERMINAL';
      agentStateText.className = 'agent-state-text active';
      speechTelemetryVal.textContent = 'KEYBOARD ACTIVE';
    } else {
      agentStateText.textContent = isTextMode ? 'TEXT TERMINAL' : 'ONLINE // BUSY';
      speechTelemetryVal.textContent = 'BUS IDLE';
      if (isTextMode) {
        agentStateText.className = 'agent-state-text active';
      } else {
        agentStateText.className = 'agent-state-text';
      }
    }
  }

  function updateConnectionStatus(status) {
    if (status === 'connected') {
      statusDot.parentElement.classList.add('connected');
      statusText.textContent = 'TELEMETRY ONLINE';
      updateOrbState('idle');
    } else {
      statusDot.parentElement.classList.remove('connected');
      statusText.textContent = 'OFFLINE // SCANNED';
      updateOrbState('offline');
    }
  }

  function toggleMute() {
    if (!room || !room.localParticipant) return;
    
    isMuted = !isMuted;
    room.localParticipant.setMicrophoneEnabled(!isMuted);
    
    if (isMuted) {
      btnMic.classList.add('muted');
      iconMicOn.classList.add('hidden');
      iconMicOff.classList.remove('hidden');
    } else {
      btnMic.classList.remove('muted');
      iconMicOn.classList.remove('hidden');
      iconMicOff.classList.add('hidden');
    }
  }

  function setMicrophoneActive(active) {
    if (!room || !room.localParticipant) return;
    isMuted = !active;
    room.localParticipant.setMicrophoneEnabled(active);
    
    if (isMuted) {
      btnMic.classList.add('muted');
      iconMicOn.classList.add('hidden');
      iconMicOff.classList.remove('hidden');
    } else {
      btnMic.classList.remove('muted');
      iconMicOn.classList.remove('hidden');
      iconMicOff.classList.add('hidden');
    }
  }

  function toggleMode() {
    isTextMode = !isTextMode;
    
    if (isTextMode) {
      btnToggleMode.classList.add('active');
      iconKeyboard.classList.add('hidden');
      iconMicToggle.classList.remove('hidden');
      chatInputContainer.classList.remove('hidden');
      chatInput.focus();
      
      // Mute client microphone
      setMicrophoneActive(false);
      
      updateOrbState('text-mode');
    } else {
      btnToggleMode.classList.remove('active');
      iconKeyboard.classList.remove('hidden');
      iconMicToggle.classList.add('hidden');
      chatInputContainer.classList.add('hidden');
      
      // Unmute client microphone
      setMicrophoneActive(true);
      
      updateOrbState('idle');
    }
  }

  async function sendChatMessage() {
    let text = chatInput.value.trim();
    if (!text) return;
    
    // Disable send temporarily to prevent double submission
    chatInput.disabled = true;
    
    try {
      if (chatSelectedFile) {
        addChatMessage('system-msg', `Uploading attachment: ${chatSelectedFile.name}...`);
        
        // 1. Read and upload file content
        const base64Content = await readFileAsBase64(chatSelectedFile);
        const uploadRes = await fetch(`${apiBase}/api/upload`, {
          method: 'POST',
          headers: getHeaders(),
          body: JSON.stringify({
            filename: chatSelectedFile.name,
            content: base64Content
          })
        });
        
        if (!uploadRes.ok) {
          const errData = await uploadRes.json();
          throw new Error(errData.detail || 'File upload failed.');
        }
        
        const uploadData = await uploadRes.json();
        const filepath = uploadData.filepath; // D:\Jarvis\uploads\filename
        
        // 2. Format message with uploaded file path
        text = `Please analyze the file uploaded at "${filepath}". Message: ${text}`;
        
        // Clear uploader state
        chatSelectedFile = null;
        chatFileUploader.value = '';
        chatAttachmentPreview.classList.add('hidden');
      }
      
      addChatMessage('user', text);
      chatInput.value = '';
      
      if (room && room.state === 'connected') {
        const encoder = new TextEncoder();
        const payload = JSON.stringify({ type: 'user_chat', text: text });
        const data = encoder.encode(payload);
        await room.localParticipant.publishData(data, { reliable: true });
      } else {
        addChatMessage('system-msg', 'No active transmission pathway.');
      }
    } catch (err) {
      console.error('Failed to send text message:', err);
      addChatMessage('system-msg', 'Failed to transmit message: ' + err.message);
    } finally {
      chatInput.disabled = false;
      chatInput.focus();
    }
  }

  // --- LiveKit WebRTC Session Integration ---
