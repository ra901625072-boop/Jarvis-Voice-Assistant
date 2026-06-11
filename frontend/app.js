// app.js — Wake Word "Jarvis" + 0.5–1s Auto-Connect

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
            if (this.tempValue) this.tempValue.innerText = `${data.temp}°C`;
            let tempPercent = ((data.temp - 30) / 60);
            tempPercent = Math.max(0, Math.min(1, tempPercent));
            if (this.tempProgress) this.tempProgress.style.transform = `scaleX(${tempPercent})`;
        });
    }

    async fetchStats() {
        if (this.connection && this.connection.isConnected()) return;
        try {
            const response = await fetch('/stats');
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

class JarvisConnection {
    constructor(ui) {
        this.ui = ui;
        this.ui.connection = this;
        this.room = null;
        this._isConnecting = false;
        this.cachedToken = null;
        this.agentIdentity = null;
    }

    isConnected() {
        return this.room && this.room.state === 'connected';
    }

    isConnecting() {
        return this._isConnecting;
    }

    async connect() {
        if (this._isConnecting || this.isConnected()) return;
        this._isConnecting = true;

        try {
            this.ui.setState('connecting');
            this.ui.addLog('Manual override accepted. Handing off to LiveKit...', 'sys');

            const response = await fetch('/token');
            if (!response.ok) throw new Error(`Server returned ${response.status}`);
            const data = await response.json();

            this.room = new LivekitClient.Room({
                adaptiveStream: true,
                dynacast: true,
            });

            this.setupListeners();
            await this.room.connect(data.url, data.token);
            this._isConnecting = false;

            this.ui.addLog('Uplink established successfully.', 'sys');
            this.ui.setState('listening');

            await this.room.localParticipant.setMicrophoneEnabled(true);
            this.ui.addLog('Microphone access granted.', 'sys');

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
            this.ui.setState(isAgentSpeaking ? 'speaking' : 'listening');
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
            window.dispatchEvent(new CustomEvent('jarvis-disconnected'));
        });
    }

    async disconnect() {
        if (this.room) {
            await this.room.disconnect();
            this.room = null;
        }
        this.ui.addLog('Uplink terminated.', 'sys');
        this.ui.setState('idle');
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    const ui = new JarvisUI();
    const connection = new JarvisConnection(ui);
    
    ui.setState('idle');
    ui.addLog('System ready. Establishing automatic uplink...', 'sys');

    window.addEventListener('beforeunload', () => {
        try {
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
