document.addEventListener('DOMContentLoaded', () => {
    // UI Elements
    const statusText = document.getElementById('status-text');
    const statusIndicator = document.getElementById('status-indicator');
    const orbContainer = document.querySelector('.orb-container');
    const agentStatusContainer = document.querySelector('.agent-status-container');
    const agentStateText = document.getElementById('agent-state-text');
    const scanningLine = document.getElementById('scanning-line');
    const errorNotification = document.getElementById('error-notification');
    const errorMessage = document.getElementById('error-message');
    const voiceWave = document.getElementById('voice-wave');
    const clockWidget = document.getElementById('clock-widget');
    const conversationPreview = document.getElementById('conversation-preview');

    const orbElement = document.querySelector('.orb');

    let currentRoom = null;

    // --- Widgets ---
    function updateClock() {
        const now = new Date();
        clockWidget.innerText = now.toLocaleTimeString('en-US', { hour12: false });
    }
    setInterval(updateClock, 1000);
    updateClock();

    // --- System Stats ---
    const cpuValue = document.getElementById('cpu-value');
    const cpuProgress = document.getElementById('cpu-progress');
    const tempValue = document.getElementById('temp-value');
    const tempProgress = document.getElementById('temp-progress');

    async function fetchStats() {
        try {
            const response = await fetch('/stats');
            if (response.ok) {
                const data = await response.json();
                if (cpuValue) cpuValue.innerText = `${Math.round(data.cpu)}%`;
                if (cpuProgress) cpuProgress.style.width = `${Math.round(data.cpu)}%`;
                
                if (tempValue) tempValue.innerText = `${data.temp}°C`;
                // Map temp 30-90 to 0-100% for progress bar
                let tempPercent = ((data.temp - 30) / 60) * 100;
                tempPercent = Math.max(0, Math.min(100, tempPercent));
                if (tempProgress) tempProgress.style.width = `${Math.round(tempPercent)}%`;
            }
        } catch (e) {
            // Ignore fetch errors to avoid console spam if server is offline
        }
    }
    setInterval(fetchStats, 2000);
    fetchStats();

    // --- Conversation Logs ---
    function addLog(msg, type = 'sys') {
        const p = document.createElement('p');
        const span = document.createElement('span');
        span.className = `log-time ${type}`;
        span.innerText = type === 'sys' ? '[SYS]' : '[JARVIS]';
        
        p.appendChild(span);
        p.appendChild(document.createTextNode(' ' + msg));
        
        conversationPreview.appendChild(p);
        
        // Auto scroll to bottom
        conversationPreview.scrollTop = conversationPreview.scrollHeight;
    }

    // --- State Management ---
    function setUIState(state, message = '') {
        // Reset classes
        statusIndicator.className = 'status';
        orbContainer.className = 'orb-container';
        agentStatusContainer.className = 'agent-status-container';
        scanningLine.classList.add('hidden');
        errorNotification.classList.add('hidden');
        voiceWave.classList.add('hidden');

        switch (state) {
            case 'idle':
                statusIndicator.classList.add('idle');
                statusText.innerText = 'Disconnected';
                agentStateText.innerText = 'System Standby';
                break;
            case 'connecting':
                statusIndicator.classList.add('connecting');
                statusText.innerText = 'Connecting...';
                orbContainer.classList.add('state-connecting');
                agentStatusContainer.classList.add('state-connecting');
                agentStateText.innerText = 'Establishing Uplink...';
                scanningLine.classList.remove('hidden');
                addLog('Attempting connection to LiveKit server...', 'sys');
                break;
            case 'listening':
                statusIndicator.classList.add('connected');
                statusText.innerText = 'Connected';
                orbContainer.classList.add('state-listening');
                agentStatusContainer.classList.add('state-listening');
                agentStateText.innerText = 'Awaiting Input';
                break;
            case 'speaking':
                statusIndicator.classList.add('connected');
                statusText.innerText = 'Connected';
                orbContainer.classList.add('state-speaking');
                agentStatusContainer.classList.add('state-speaking');
                agentStateText.innerText = 'Transmitting...';
                voiceWave.classList.remove('hidden');
                break;
            case 'error':
                statusIndicator.classList.add('idle');
                statusText.innerText = 'Disconnected';
                agentStateText.innerText = 'Connection Failed';
                errorNotification.classList.remove('hidden');
                errorMessage.innerText = message || 'Connection failed.';
                addLog('Connection failed: ' + message, 'sys');
                break;
        }
    }

    // --- Orb Interaction ---
    orbElement.addEventListener('click', () => {
        if (statusIndicator.classList.contains('idle')) {
            addLog('Orb tapped. Initializing connection...', 'sys');
            connectToLiveKit();
        } else {
            addLog('Orb tapped. Terminating connection...', 'sys');
            disconnectFromLiveKit();
        }
    });

    async function connectToLiveKit() {
        try {
            setUIState('connecting');

            // Fetch token from local backend server
            const response = await fetch('/token');
            if (!response.ok) {
                throw new Error(`Server returned ${response.status}`);
            }
            // Abort if user clicked disconnect while fetching
            if (!statusIndicator.classList.contains('connecting')) {
                return;
            }
            const data = await response.json();
            const token = data.token;
            const wsUrl = data.url;
            
            // Initialize room
            const room = new LivekitClient.Room({
                adaptiveStream: true,
                dynacast: true,
            });
            currentRoom = room;

            // Set up event listeners for state changes
            room.on(LivekitClient.RoomEvent.ParticipantConnected, (participant) => {
                console.log('Participant connected:', participant.identity);
                addLog('Participant connected: ' + participant.identity, 'sys');
            });

            room.on(LivekitClient.RoomEvent.ActiveSpeakersChanged, (speakers) => {
                const isAgentSpeaking = speakers.some(p => p.identity !== room.localParticipant.identity);
                if (isAgentSpeaking) {
                    setUIState('speaking');
                } else {
                    setUIState('listening');
                }
            });

            // Handle Transcriptions (what Jarvis is saying)
            room.on(LivekitClient.RoomEvent.TranscriptionReceived, (segments, participant) => {
                if (!participant || participant.identity === room.localParticipant.identity) return;
                for (const segment of segments) {
                    // Check both common properties for LiveKit transcription completeness
                    if (segment.isFinal || segment.final) {
                        addLog(segment.text, 'jarvis');
                    }
                }
            });

            // Fallback: handle data messages if agent sends raw text
            room.on(LivekitClient.RoomEvent.DataReceived, (payload, participant, kind, topic) => {
                if (!participant || participant.identity === room.localParticipant.identity) return;
                try {
                    const text = new TextDecoder().decode(payload);
                    // Filter out raw JSON strings just in case
                    if (!text.startsWith('{')) {
                        addLog(text, 'jarvis');
                    }
                } catch (e) {}
            });

            // Handle incoming audio tracks from the agent
            room.on(LivekitClient.RoomEvent.TrackSubscribed, (track, publication, participant) => {
                if (track.kind === LivekitClient.Track.Kind.Audio) {
                    const audioElement = track.attach();
                    document.body.appendChild(audioElement);
                    addLog('Audio stream established.', 'sys');
                }
            });

            // Connect to the room
            await room.connect(wsUrl, token);
            
            // Connected successfully
            addLog('Uplink established successfully.', 'sys');
            setUIState('listening');
            
            // Request microphone access to interact
            await room.localParticipant.enableCameraAndMicrophone();
            addLog('Microphone access granted.', 'sys');

        } catch (error) {
            console.error('Connection error:', error);
            setUIState('error', error.message);
        }
    }

    async function disconnectFromLiveKit() {
        if (currentRoom) {
            await currentRoom.disconnect();
            currentRoom = null;
        }
        addLog('Uplink terminated by user.', 'sys');
        setUIState('idle');
    }
});
