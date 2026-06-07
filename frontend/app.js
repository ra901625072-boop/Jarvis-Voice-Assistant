// app.js - Refactored Object-Oriented Logic for J.A.R.V.I.S. Dashboard

class JarvisUI {
    constructor() {
        this.initElements();
        this.bindEvents();
        this.initClock();
        this.startStatsLoop();
    }

    initElements() {
        this.statusText = document.getElementById('status-text');
        this.statusIndicator = document.getElementById('status-indicator');
        this.orbContainer = document.querySelector('.orb-container');
        this.agentStatusContainer = document.querySelector('.agent-status-container');
        this.agentStateText = document.getElementById('agent-state-text');
        this.scanningLine = document.getElementById('scanning-line');
        this.errorNotification = document.getElementById('error-notification');
        this.errorMessage = document.getElementById('error-message');
        this.voiceWave = document.getElementById('voice-wave');
        this.clockWidget = document.getElementById('clock-widget');
        this.conversationPreview = document.getElementById('conversation-preview');
        this.orbElement = document.getElementById('ai-orb');

        // System Stats
        this.cpuValue = document.getElementById('cpu-value');
        this.cpuProgress = document.getElementById('cpu-progress');
        this.tempValue = document.getElementById('temp-value');
        this.tempProgress = document.getElementById('temp-progress');
    }

    bindEvents() {
        this.orbElement.addEventListener('click', () => {
            if (navigator.vibrate) navigator.vibrate(50);
            
            if (this.statusIndicator.classList.contains('idle')) {
                this.addLog('Orb tapped. Initializing connection...', 'sys');
                if (this.onConnect) this.onConnect();
            } else {
                this.addLog('Orb tapped. Terminating connection...', 'sys');
                if (this.onDisconnect) this.onDisconnect();
            }
        });
    }

    initClock() {
        const update = () => {
            const now = new Date();
            this.clockWidget.innerText = now.toLocaleTimeString('en-US', { hour12: false });
            setTimeout(() => requestAnimationFrame(update), 1000);
        };
        requestAnimationFrame(update);
    }

    async fetchStats() {
        try {
            const response = await fetch('/stats');
            if (response.ok) {
                const data = await response.json();
                
                requestAnimationFrame(() => {
                    if (this.cpuValue) this.cpuValue.innerText = `${Math.round(data.cpu)}%`;
                    if (this.cpuProgress) this.cpuProgress.style.transform = `scaleX(${data.cpu / 100})`;
                    
                    if (this.tempValue) this.tempValue.innerText = `${data.temp}°C`;
                    let tempPercent = ((data.temp - 30) / 60);
                    tempPercent = Math.max(0, Math.min(1, tempPercent));
                    if (this.tempProgress) this.tempProgress.style.transform = `scaleX(${tempPercent})`;
                });
            }
        } catch (e) {
            // Silently ignore stat errors to prevent log spam
        }
    }

    startStatsLoop() {
        this.fetchStats();
        setInterval(() => this.fetchStats(), 2000);
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
            this.conversationPreview.scrollTop = this.conversationPreview.scrollHeight;
        });
    }

    setState(state, message = '') {
        requestAnimationFrame(() => {
            // Reset state classes
            this.statusIndicator.className = 'status';
            this.orbContainer.className = 'orb-container';
            this.agentStatusContainer.className = 'agent-status-container';
            this.scanningLine.classList.add('hidden');
            this.errorNotification.classList.add('hidden');
            this.voiceWave.classList.add('hidden');
            this.orbElement.className = 'orb';

            switch (state) {
                case 'idle':
                    this.statusIndicator.classList.add('idle');
                    this.statusText.innerText = 'Disconnected';
                    this.agentStateText.innerText = 'System Standby';
                    this.orbElement.classList.add('idle');
                    break;
                case 'connecting':
                    this.statusIndicator.classList.add('connecting');
                    this.statusText.innerText = 'Connecting...';
                    this.orbContainer.classList.add('state-connecting');
                    this.agentStatusContainer.classList.add('state-connecting');
                    this.agentStateText.innerText = 'Establishing Uplink...';
                    this.scanningLine.classList.remove('hidden');
                    break;
                case 'listening':
                    this.statusIndicator.classList.add('connected');
                    this.statusText.innerText = 'Connected';
                    this.orbContainer.classList.add('state-listening');
                    this.agentStatusContainer.classList.add('state-listening');
                    this.agentStateText.innerText = 'Awaiting Input';
                    break;
                case 'speaking':
                    this.statusIndicator.classList.add('connected');
                    this.statusText.innerText = 'Connected';
                    this.orbContainer.classList.add('state-speaking');
                    this.agentStatusContainer.classList.add('state-speaking');
                    this.agentStateText.innerText = 'Transmitting...';
                    this.voiceWave.classList.remove('hidden');
                    break;
                case 'error':
                    this.statusIndicator.classList.add('idle');
                    this.statusText.innerText = 'Disconnected';
                    this.agentStateText.innerText = 'Connection Failed';
                    this.errorNotification.classList.remove('hidden');
                    this.errorMessage.innerText = message || 'Connection failed.';
                    this.orbElement.classList.add('idle');
                    break;
            }
        });
    }
}

class JarvisConnection {
    constructor(ui) {
        this.ui = ui;
        this.room = null;
    }

    async connect() {
        try {
            this.ui.setState('connecting');
            this.ui.addLog('Attempting connection to LiveKit server...', 'sys');

            const response = await fetch('/token');
            if (!response.ok) {
                throw new Error(`Server returned ${response.status}`);
            }

            if (!this.ui.statusIndicator.classList.contains('connecting')) {
                return; // User aborted
            }

            const data = await response.json();
            
            this.room = new LivekitClient.Room({
                adaptiveStream: true,
                dynacast: true,
            });

            this.setupListeners();
            await this.room.connect(data.url, data.token);

            if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
            this.ui.addLog('Uplink established successfully.', 'sys');
            this.ui.setState('listening');
            
            await this.room.localParticipant.enableCameraAndMicrophone();
            this.ui.addLog('Microphone access granted.', 'sys');

        } catch (error) {
            if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
            console.error('Connection error:', error);
            this.ui.setState('error', error.message);
            this.ui.addLog('Connection failed: ' + error.message, 'sys');
        }
    }

    setupListeners() {
        this.room.on(LivekitClient.RoomEvent.ParticipantConnected, (participant) => {
            this.ui.addLog(`Participant connected: ${participant.identity}`, 'sys');
        });

        this.room.on(LivekitClient.RoomEvent.ActiveSpeakersChanged, (speakers) => {
            const isAgentSpeaking = speakers.some(p => p.identity !== this.room.localParticipant.identity);
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
                if (!text.startsWith('{')) {
                    this.ui.addLog(text, 'jarvis');
                }
            } catch (e) {}
        });

        this.room.on(LivekitClient.RoomEvent.TrackSubscribed, (track) => {
            if (track.kind === LivekitClient.Track.Kind.Audio) {
                const audioElement = track.attach();
                document.body.appendChild(audioElement);
                this.ui.addLog('Audio stream established.', 'sys');
            }
        });
    }

    async disconnect() {
        if (this.room) {
            await this.room.disconnect();
            this.room = null;
        }
        this.ui.addLog('Uplink terminated by user.', 'sys');
        this.ui.setState('idle');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const ui = new JarvisUI();
    const connection = new JarvisConnection(ui);

    ui.onConnect = () => connection.connect();
    ui.onDisconnect = () => connection.disconnect();
});
