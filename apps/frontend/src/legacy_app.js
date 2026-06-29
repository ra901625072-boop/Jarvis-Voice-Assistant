// app.js — Wake Word "Jarvis" + Auto-Connect + Standby Mode

// ─── Wake Word Detector ────────────────────────────────────────────
// Uses the browser's built-in SpeechRecognition API to listen for "Jarvis"
// locally without sending audio to the server. When detected, fires onWakeWord().
class WakeWordDetector {
    constructor(onWakeWord) {
        this.onWakeWord = onWakeWord;
        this.recognition = null;
        this._running = false;
        this._stopped = true; // explicitly stopped by user

        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            console.warn('SpeechRecognition API not available. Wake word detection disabled.');
            return;
        }

        this.recognition = new SpeechRecognition();
        this.recognition.continuous = true;
        this.recognition.interimResults = true;
        this.recognition.lang = 'en-US';
        this.recognition.maxAlternatives = 3;

        this.recognition.onresult = (event) => {
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const result = event.results[i];
                for (let j = 0; j < result.length; j++) {
                    const transcript = result[j].transcript.toLowerCase().trim();
                    if (transcript.includes('jarvis')) {
                        console.log('[WakeWord] Detected "Jarvis" in:', transcript);
                        this.stop();
                        this.onWakeWord();
                        return;
                    }
                }
            }
        };

        this.recognition.onend = () => {
            this._running = false;
            // Auto-restart if not explicitly stopped
            if (!this._stopped) {
                setTimeout(() => {
                    if (!this._stopped) this._startInternal();
                }, 300);
            }
        };

        this.recognition.onerror = (event) => {
            // 'no-speech' and 'aborted' are normal — just restart silently
            if (event.error === 'no-speech' || event.error === 'aborted') return;
            console.warn('[WakeWord] Error:', event.error);
        };
    }

    _startInternal() {
        if (!this.recognition || this._running) return;
        try {
            this._running = true;
            this.recognition.start();
        } catch (e) {
            this._running = false;
            // DOMException if already started — ignore
        }
    }

    start() {
        if (!this.recognition) return;
        this._stopped = false;
        this._startInternal();
    }

    stop() {
        if (!this.recognition) return;
        this._stopped = true;
        this._running = false;
        try {
            this.recognition.stop();
        } catch (e) {}
    }
}

// ─── Jarvis UI ─────────────────────────────────────────────────────
class JarvisUI {
    constructor() {
        this.initElements();
        this.initClock();
        this.startStatsLoop();
    }

    initElements() {
        this.statusText = document.getElementById('status-text');
        this.statusIndicator = document.getElementById('status-indicator');
        this.orbContainer = document.querySelector('.orb-container');
        this.agentStatusContainer = document.querySelector('.agent-status-container');
        this.agentStateText = document.getElementById('agent-state-text');
        this.errorNotification = document.getElementById('error-notification');
        this.errorMessage = document.getElementById('error-message');
        this.clockWidget = document.getElementById('clock-widget');
        this.conversationPreview = document.getElementById('conversation-preview');
        this.orbElement = document.getElementById('ai-orb');
        this.goldenWave = document.getElementById('golden-wave');

        this.cpuValue = document.getElementById('cpu-value');
        this.cpuProgress = document.getElementById('cpu-progress');
        this.tempValue = document.getElementById('temp-value');
        this.tempProgress = document.getElementById('temp-progress');
    }

    initClock() {
        const update = () => {
            const now = new Date();
            this.clockWidget.innerText = now.toLocaleTimeString('en-US', { hour12: false });
            setTimeout(() => requestAnimationFrame(update), 1000);
        };
        requestAnimationFrame(update);
    }

    updateStatsUI(data) {
        requestAnimationFrame(() => {
            if (this.cpuValue) this.cpuValue.innerText = `${Math.round(data.cpu)}%`;
            if (this.cpuProgress) this.cpuProgress.style.transform = `scaleX(${data.cpu / 100})`;
            
            if (data.temp !== null && data.temp !== undefined && data.temp_source !== "unavailable") {
                if (this.tempValue) this.tempValue.innerText = `${data.temp}°C`;
                let tempPercent = ((data.temp - 30) / 60);
                tempPercent = Math.max(0, Math.min(1, tempPercent));
                if (this.tempProgress) this.tempProgress.style.transform = `scaleX(${tempPercent})`;
            } else {
                if (this.tempValue) this.tempValue.innerText = 'N/A';
                if (this.tempProgress) this.tempProgress.style.transform = 'scaleX(0)';
            }
        });
    }

    async fetchStats() {
        if (this.connection && this.connection.isConnected()) return;
        const apiKey = (this.connection && this.connection.apiKey) || '';
        if (!apiKey) return;
        try {
            const response = await fetch('/stats', {
                headers: { 'Authorization': apiKey }
            });
            if (response.ok) {
                const data = await response.json();
                this.updateStatsUI(data);
            }
        } catch (e) {}
    }

    startStatsLoop() {
        this.fetchStats();
        setInterval(() => this.fetchStats(), 5000);
    }

    addLog(msg, type = 'sys') {
        requestAnimationFrame(() => {
            const p = document.createElement('p');
            const span = document.createElement('span');
            span.className = `log-time ${type}`;
            span.innerText = type === 'sys' ? '[SYS]' : '[JARVIS]';
            p.appendChild(span);
            p.appendChild(document.createTextNode(' ' + msg));
            this.conversationPreview.appendChild(p);
            
            const MAX_LOGS = 100;
            while (this.conversationPreview.children.length > MAX_LOGS) {
                this.conversationPreview.removeChild(this.conversationPreview.firstChild);
            }
            
            this.conversationPreview.scrollTop = this.conversationPreview.scrollHeight;
        });
    }

    setState(state, message = '') {
        // Cancel any pending frame to prevent visual flicker/shift
        if (this._pendingFrame) {
            cancelAnimationFrame(this._pendingFrame);
        }
        
        this._pendingFrame = requestAnimationFrame(() => {
            this._pendingFrame = null;

            if (this.statusIndicator) this.statusIndicator.className = 'connection';
            if (this.orbContainer) this.orbContainer.className = 'orb-container';
            if (this.agentStatusContainer) this.agentStatusContainer.className = 'agent-status-container';
            if (this.errorNotification) this.errorNotification.classList.add('hidden');
            if (this.orbElement) this.orbElement.className = 'orb';
            if (this.goldenWave) this.goldenWave.classList.remove('active');

            switch (state) {
                case 'connecting':
                    if (this.statusIndicator) this.statusIndicator.classList.add('connecting');
                    if (this.statusText) this.statusText.innerText = 'Connecting...';
                    if (this.orbContainer) this.orbContainer.classList.add('state-connecting');
                    if (this.agentStatusContainer) this.agentStatusContainer.classList.add('state-connecting');
                    if (this.agentStateText) this.agentStateText.innerText = 'Establishing Uplink...';
                    break;
                case 'standby':
                    if (this.statusIndicator) this.statusIndicator.classList.add('standby');
                    if (this.statusText) this.statusText.innerText = 'Standby';
                    if (this.orbContainer) this.orbContainer.classList.add('state-idle');
                    if (this.agentStatusContainer) this.agentStatusContainer.classList.add('state-idle');
                    if (this.agentStateText) this.agentStateText.innerText = 'Say "Jarvis" to activate';
                    break;
                case 'listening':
                    if (this.statusIndicator) this.statusIndicator.classList.add('connected');
                    if (this.statusText) this.statusText.innerText = 'Connected';
                    if (this.orbContainer) this.orbContainer.classList.add('state-listening');
                    if (this.agentStatusContainer) this.agentStatusContainer.classList.add('state-listening');
                    if (this.agentStateText) this.agentStateText.innerText = 'Awaiting Input';
                    break;
                case 'speaking':
                    if (this.statusIndicator) this.statusIndicator.classList.add('connected');
                    if (this.statusText) this.statusText.innerText = 'Connected';
                    if (this.orbContainer) this.orbContainer.classList.add('state-speaking');
                    if (this.agentStatusContainer) this.agentStatusContainer.classList.add('state-speaking');
                    if (this.agentStateText) this.agentStateText.innerText = 'Transmitting...';
                    if (this.goldenWave) this.goldenWave.classList.add('active');
                    break;
                case 'processing':
                    if (this.statusIndicator) this.statusIndicator.classList.add('connected');
                    if (this.statusText) this.statusText.innerText = 'Connected';
                    if (this.orbContainer) this.orbContainer.classList.add('state-listening');
                    if (this.agentStatusContainer) this.agentStatusContainer.classList.add('state-listening');
                    if (this.agentStateText) this.agentStateText.innerText = 'Processing...';
                    if (this.goldenWave) this.goldenWave.classList.add('active');
                    break;
                case 'error':
                    if (this.statusIndicator) this.statusIndicator.classList.add('idle');
                    if (this.statusText) this.statusText.innerText = 'Disconnected';
                    if (this.agentStateText) this.agentStateText.innerText = 'Connection Failed';
                    if (this.errorNotification) this.errorNotification.classList.remove('hidden');
                    if (this.errorMessage) this.errorMessage.innerText = message || 'Connection failed.';
                    if (this.orbElement) this.orbElement.classList.add('idle');
                    if (this.orbContainer) this.orbContainer.classList.add('state-error');
                    if (this.agentStatusContainer) this.agentStatusContainer.classList.add('state-error');
                    break;
                case 'idle':
                default:
                    if (this.statusIndicator) this.statusIndicator.classList.add('idle');
                    if (this.statusText) this.statusText.innerText = 'Disconnected';
                    if (this.agentStateText) this.agentStateText.innerText = 'System Standby — Click J.A.R.V.I.S to connect';
                    if (this.orbElement) this.orbElement.classList.add('idle');
                    if (this.orbContainer) this.orbContainer.classList.add('state-idle');
                    if (this.agentStatusContainer) this.agentStatusContainer.classList.add('state-idle');
                    break;
            }
        });
    }
}

// ─── Jarvis Connection ─────────────────────────────────────────────
class JarvisConnection {
    constructor(ui) {
        this.ui = ui;
        this.ui.connection = this;
        this.room = null;
        this._isConnecting = false;
        this.cachedToken = null;
        this.agentIdentity = null;
        this.apiKey = '';

        // Wake word activation state
        this._isActivated = false;         // true = mic is hot, listening for command
        this._introCompleted = false;      // true = intro speech has finished
        this._silenceTimer = null;          // timer to auto-deactivate after agent stops speaking
        this._agentSpeaking = false;       // tracks if agent is currently speaking
        this.SILENCE_TIMEOUT_MS = 3000;    // 3 seconds of silence before standby
    }

    isConnected() {
        return this.room && this.room.state === 'connected';
    }

    isConnecting() {
        return this._isConnecting;
    }

    // Enable the LiveKit mic — audio flows to the agent
    async enableMic() {
        if (!this.room) return;
        try {
            await this.room.localParticipant.setMicrophoneEnabled(true);
            console.log('[Mic] Enabled — listening for command');
        } catch (e) {
            console.error('[Mic] Failed to enable:', e);
        }
    }

    // Disable the LiveKit mic — no audio flows to the agent
    async disableMic() {
        if (!this.room) return;
        try {
            await this.room.localParticipant.setMicrophoneEnabled(false);
            console.log('[Mic] Disabled — standby mode');
        } catch (e) {
            console.error('[Mic] Failed to disable:', e);
        }
    }

    // Called when wake word "Jarvis" is detected
    async activate() {
        if (this._isActivated || !this.isConnected()) return;
        this._isActivated = true;
        this._clearSilenceTimer();
        
        this.ui.addLog('Wake word detected — listening...', 'sys');
        this.ui.setState('listening');
        await this.enableMic();
    }

    // Called after silence timeout — go back to standby
    async deactivate() {
        if (!this._isActivated) return;
        this._isActivated = false;
        this._clearSilenceTimer();

        await this.disableMic();
        this.ui.setState('standby');
        this.ui.addLog('Returning to standby mode.', 'sys');

        // Resume wake word detection
        if (this.wakeWordDetector) {
            this.wakeWordDetector.start();
        }
    }

    _clearSilenceTimer() {
        if (this._silenceTimer) {
            clearTimeout(this._silenceTimer);
            this._silenceTimer = null;
        }
    }

    // Start the silence countdown — if agent stays silent for SILENCE_TIMEOUT_MS, deactivate
    _startSilenceTimer() {
        this._clearSilenceTimer();
        this._silenceTimer = setTimeout(() => {
            if (this._isActivated && !this._agentSpeaking) {
                this.deactivate();
            }
        }, this.SILENCE_TIMEOUT_MS);
    }

    async connect() {
        if (this._isConnecting || this.isConnected()) return;
        
        if (!this.apiKey) {
            this.showApiKeyModal();
            return;
        }
        
        this._isConnecting = true;

        try {
            this.ui.setState('connecting');
            this.ui.addLog('Manual override accepted. Handing off to LiveKit...', 'sys');

            // Authenticate with FastAPI backend
            try {
                const tokenResponse = await fetch('http://localhost:8001/api/auth/token', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ api_key: this.apiKey })
                });
                if (tokenResponse.ok) {
                    const tokenData = await tokenResponse.json();
                    this.jwtToken = tokenData.token;
                    window.dispatchEvent(new CustomEvent('jarvis-authorized', {
                        detail: { apiKey: this.apiKey, jwtToken: this.jwtToken }
                    }));
                }
            } catch (e) {
                console.error("FastAPI authentication failed:", e);
            }

            const response = await fetch('/token', {
                headers: { 'Authorization': this.apiKey }
            });
            if (response.status === 401) {
                this._isConnecting = false;
                this.apiKey = '';
                this.ui.setState('idle');
                this.ui.addLog('Authentication failed: Invalid API Key.', 'sys');
                this.showApiKeyModal("Invalid API Key. Please authorize again.");
                return;
            }
            if (!response.ok) throw new Error(`Server returned ${response.status}`);
            const data = await response.json();

            this.room = new LivekitClient.Room({
                adaptiveStream: true,
                dynacast: true,
                audioCaptureDefaults: {
                    autoGainControl: true,
                    echoCancellation: true,
                    noiseSuppression: true,
                }
            });

            this.setupListeners();
            await this.room.connect(data.url, data.token);
            this._isConnecting = false;

            this.ui.addLog('Uplink established successfully.', 'sys');

            // Enable mic initially so the agent can deliver the intro
            // The mic will be disabled after the intro completes
            this._introCompleted = false;
            this._isActivated = true; // temporarily activated for intro
            await this.room.localParticipant.setMicrophoneEnabled(true);
            this.ui.addLog('Microphone access granted.', 'sys');
            this.ui.setState('listening');

        } catch (error) {
            this._isConnecting = false;
            console.error('Connection failed');
            console.error('Message:', error.message);
            console.error('Stack:', error.stack);
            this.ui.setState('error', error.message);
            this.ui.addLog('Connection failed: ' + error.message, 'sys');
            throw error;
        }
    }

    setupListeners() {
        this.room.on(LivekitClient.RoomEvent.ParticipantConnected, (participant) => {
            this.ui.addLog(`Participant connected: ${participant.identity}`, 'sys');
            if (participant.identity !== this.room.localParticipant.identity) {
                this.agentIdentity = participant.identity;
            }
        });

        this.room.on(LivekitClient.RoomEvent.ActiveSpeakersChanged, (speakers) => {
            const isAgentSpeaking = speakers.some(p => p.identity === this.agentIdentity);
            
            if (isAgentSpeaking) {
                this._agentSpeaking = true;
                this._clearSilenceTimer();
                this.ui.setState('speaking');
            } else {
                // Agent stopped speaking
                if (this._agentSpeaking) {
                    this._agentSpeaking = false;

                    // If intro hasn't completed yet, this is the end of the intro
                    if (!this._introCompleted) {
                        this._introCompleted = true;
                        // After intro finishes, go to standby
                        this._isActivated = false;
                        this.disableMic();
                        this.ui.setState('standby');
                        this.ui.addLog('Intro complete — entering standby. Say "Jarvis" to activate.', 'sys');
                        
                        // Start wake word detection
                        if (this.wakeWordDetector) {
                            this.wakeWordDetector.start();
                        }
                    } else if (this._isActivated) {
                        // Agent finished responding to a command — start silence timer
                        this.ui.setState('listening');
                        this._startSilenceTimer();
                    }
                }
            }
        });

        this.room.on(LivekitClient.RoomEvent.TranscriptionReceived, (segments, participant) => {
            if (!participant || participant.identity === this.room.localParticipant.identity) return;
            for (const segment of segments) {
                if (segment.isFinal || segment.final) {
                    this.ui.addLog(segment.text, 'jarvis');
                }
            }
        });

        this.room.on(LivekitClient.RoomEvent.DataReceived, (payload, participant) => {
            if (!participant || participant.identity === this.room.localParticipant.identity) return;
            try {
                const text = new TextDecoder().decode(payload);
                if (text.startsWith('{')) {
                    const data = JSON.parse(text);
                    if (data.type === 'processing_start') {
                        // Agent is processing — reset silence timer, keep mic active
                        this._clearSilenceTimer();
                        this.ui.setState('processing');
                    } else if (data.type === 'stats') {
                        this.ui.updateStatsUI(data);
                    }
                } else {
                    this.ui.addLog(text, 'jarvis');
                }
            } catch (e) {}
        });

        this.room.on(LivekitClient.RoomEvent.TrackSubscribed, (track) => {
            if (track.kind === LivekitClient.Track.Kind.Audio) {
                const audioElement = track.attach();
                audioElement.style.position = 'absolute';
                audioElement.style.opacity = '0';
                audioElement.style.pointerEvents = 'none';
                audioElement.setAttribute('aria-hidden', 'true');
                document.body.appendChild(audioElement);
                this.ui.addLog('Audio stream established.', 'sys');
            }
        });

        this.room.on(LivekitClient.RoomEvent.TrackUnsubscribed, (track) => {
            if (track.kind === LivekitClient.Track.Kind.Audio) {
                track.detach().forEach(el => el.remove());
            }
        });

        this.room.on(LivekitClient.RoomEvent.Disconnected, () => {
            this.ui.addLog('LiveKit disconnected.', 'sys');
            this.ui.setState('idle');
            this.room = null;
            this._isActivated = false;
            this._introCompleted = false;
            this._clearSilenceTimer();
            window.dispatchEvent(new CustomEvent('jarvis-disconnected'));
        });
    }

    async disconnect() {
        this._clearSilenceTimer();
        if (this.wakeWordDetector) {
            this.wakeWordDetector.stop();
        }
        if (this.room) {
            await this.room.disconnect();
            this.room = null;
        }
        this._isActivated = false;
        this._introCompleted = false;
        this.ui.addLog('Uplink terminated.', 'sys');
        this.ui.setState('idle');
    }

    showApiKeyModal(errorMessage = '') {
        const modal = document.getElementById('api-key-modal');
        const input = document.getElementById('api-key-input');
        const btn = document.getElementById('save-api-key-btn');
        const errorMsg = document.getElementById('auth-error-msg');
        
        if (!modal) return;
        
        modal.classList.remove('hidden');
        input.value = '';
        input.focus();
        
        if (errorMessage) {
            errorMsg.innerText = errorMessage;
            errorMsg.classList.remove('hidden');
        } else {
            errorMsg.classList.add('hidden');
        }
        
        btn.onclick = () => {
            const val = input.value.trim();
            if (val) {
                this.apiKey = val;
                modal.classList.add('hidden');
                errorMsg.classList.add('hidden');
                this.connect();
            } else {
                errorMsg.innerText = "API Key cannot be empty.";
                errorMsg.classList.remove('hidden');
            }
        };
        
        input.onkeydown = (e) => {
            if (e.key === 'Enter') {
                btn.click();
            }
        };
    }
}

// ─── Boot ──────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    const ui = new JarvisUI();
    const connection = new JarvisConnection(ui);
    
    ui.setState('idle');
    ui.addLog('System ready. Establishing automatic uplink...', 'sys');

    // Initialize upgrade managers
    const taskFeed = new TaskFeedManager();
    const agentStatus = new AgentStatusManager();
    const workflowBuilder = new WorkflowBuilder();
    const metricsCharts = new MetricsCharts();

    // Hook API key & JWT token authorization event
    window.addEventListener('jarvis-authorized', (e) => {
        const { apiKey, jwtToken } = e.detail;
        taskFeed.setAuth(apiKey, jwtToken);
        agentStatus.setAuth(apiKey, jwtToken);
        workflowBuilder.setAuth(apiKey, jwtToken);
        metricsCharts.setAuth(apiKey, jwtToken);
    });

    // Hook tab switcher
    const tabs = {
        'tab-hud': 'hud-view',
        'tab-workflows': 'workflows-view',
        'tab-metrics': 'metrics-view'
    };
    Object.keys(tabs).forEach(tabId => {
        const tabBtn = document.getElementById(tabId);
        if (tabBtn) {
            tabBtn.addEventListener('click', () => {
                document.querySelectorAll('.nav-tab').forEach(btn => btn.classList.remove('active'));
                tabBtn.classList.add('active');

                Object.values(tabs).forEach(viewId => {
                    const view = document.getElementById(viewId);
                    if (view) {
                        if (viewId === tabs[tabId]) {
                            view.classList.remove('hidden');
                        } else {
                            view.classList.add('hidden');
                        }
                    }
                });
            });
        }
    });

    // Initialize wake word detector
    const wakeWordDetector = new WakeWordDetector(() => {
        connection.activate();
    });
    connection.wakeWordDetector = wakeWordDetector;

    window.addEventListener('beforeunload', () => {
        try {
            wakeWordDetector.stop();
            metricsCharts.cleanup();
            if (connection.room) {
                connection.room.disconnect();
            }
        } catch {}
    });

    const brandElement = document.querySelector('.brand');
    if (brandElement) {
        brandElement.addEventListener('click', async () => {
            if (connection.isConnected() || connection.isConnecting()) {
                await connection.disconnect();
            } else {
                try {
                    await connection.connect();
                } catch (e) {
                    console.error('Connection failed via click', e);
                }
            }
        });
    }

    // Auto-connect automatically when page loads
    setTimeout(async () => {
        if (!connection.isConnected() && !connection.isConnecting()) {
            try {
                await connection.connect();
            } catch (e) {
                console.error('Auto-connect failed', e);
                ui.addLog('Auto-connect failed. Click J.A.R.V.I.S to retry.', 'sys');
            }
        }
    }, 500);
});
