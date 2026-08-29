  async function connectToLiveKit(apiKey) {
    try {
      // 1. Fetch token from Flask backend (/token)
      const tokenUrl = `${flaskBase}/token`;
      const res = await fetch(tokenUrl, {
        method: 'GET',
        headers: {
          'Authorization': apiKey
        }
      });
      
      if (!res.ok) {
        throw new Error(`Authentication with WebRTC gateway failed (${res.status})`);
      }
      
      const data = await res.json();
      if (!data.token || !data.url) {
        throw new Error('Invalid Livekit credentials returned.');
      }
      
      // 2. Initialize LiveKit Room
      const LK = window.LivekitClient || window.LiveKit || window.LiveKitClient || window.livekitClient;
      if (!LK) {
        throw new Error('LiveKit Client libraries failed to load.');
      }
      
      room = new LK.Room({
        adaptiveStream: true,
        dynacast: true,
        publishDefaults: {
          simulcast: false,
          red: false,
          dtx: true,
        }
      });
      
      // 3. Bind LiveKit events
      room
        .on(LK.RoomEvent.Connected, () => {
          updateConnectionStatus('connected');
          
          // Switch display
          loginScreen.classList.remove('active');
          setTimeout(() => {
            loginScreen.classList.add('hidden');
            dashboardScreen.classList.remove('hidden');
          }, 300);
          
          // Publish mic stream
          room.localParticipant.setMicrophoneEnabled(true);
        })
        .on(LK.RoomEvent.Reconnecting, () => {
          console.warn('LiveKit room reconnecting...');
          statusDot.parentElement.classList.remove('connected');
          statusText.textContent = 'RECONNECTING...';
          updateOrbState('thinking');
        })
        .on(LK.RoomEvent.Reconnected, () => {
          console.log('LiveKit room reconnected successfully.');
          updateConnectionStatus('connected');
        })
        .on(LK.RoomEvent.Disconnected, () => {
          updateConnectionStatus('disconnected');
          disconnect();
        })
        .on(LK.RoomEvent.TrackSubscribed, (track) => {
          if (track.kind === LK.Track.Kind.Audio) {
            track.attach(remoteAudio);
            updateOrbState('speaking');
            if (track.mediaStream) {
              initAudioTelemetry(track.mediaStream, false);
            }
          }
        })
        .on(LK.RoomEvent.TrackUnsubscribed, (track) => {
          if (track.kind === LK.Track.Kind.Audio) {
            track.detach();
            updateOrbState('idle');
          }
        })
        .on(LK.RoomEvent.LocalTrackPublished, (publication) => {
          if (publication.track.kind === LK.Track.Kind.Audio) {
            if (publication.track.mediaStream) {
              initAudioTelemetry(publication.track.mediaStream, true);
            }
          }
        })
        .on(LK.RoomEvent.ActiveSpeakersChanged, (speakers) => {
          const isAgentSpeaking = speakers.some(s => s !== room.localParticipant);
          const isUserSpeaking = speakers.some(s => s === room.localParticipant);
          
          if (isAgentSpeaking) {
            updateOrbState('speaking');
          } else if (isUserSpeaking && !isMuted) {
            updateOrbState('listening');
          } else {
            updateOrbState('idle');
          }
        })
        .on(LK.RoomEvent.DataReceived, (payload) => {
          try {
            const decoder = new TextDecoder();
            const text = decoder.decode(payload);
            let msg = text;
            try {
              const obj = JSON.parse(text);
              
              // Remove processing indicator on incoming updates except when setting it
              if (obj.type !== 'processing_start') {
                removeProcessingIndicator();
              }

              if (obj.type === 'agent_state') {
                updateOrbState(obj.state);
                return;
              }
              if (obj.type === 'thought' || obj.type === 'reasoning') {
                addReasoningNode(obj.agent || 'SYSTEM', obj.text);
                return;
              }
              if (obj.type === 'processing_start') {
                showProcessingIndicator();
                updateOrbState('thinking');
                return;
              }
              if (obj.type === 'transcript') {
                addChatMessage('agent', obj.text);
                return;
              }
              if (obj.type === 'status') {
                addChatMessage('system-msg', obj.message);
                return;
              }
              if (obj.type === 'co_task_update') {
                addChatMessage('system-msg', `[CO-TASK] ${obj.description}`);
                return;
              }
              msg = obj.text || obj.message || text;
            } catch (e) {}
            addChatMessage('agent', msg);
          } catch (e) {
            console.error('Failed to decode incoming LiveKit payload:', e);
          }
        });
        
      // Connect LiveKit Room
      await room.connect(data.url, data.token);
      
    } catch (err) {
      console.error(err);
      showError(err.message || 'WebRTC connection failed.');
      btnConnect.disabled = false;
      btnConnect.querySelector('span').textContent = 'Establish Connection';
    }
  }

  // --- Web Audio Amplitude Telemetry Analyser ---
  function initAudioTelemetry(stream, isLocal) {
    try {
      if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 64;
      source.connect(analyser);
      if (isLocal) {
        localAnalyser = analyser;
      } else {
        remoteAnalyser = analyser;
      }
    } catch (e) {
      console.warn("Failed to init audio telemetry:", e);
    }
  }

  function getActiveAmplitude() {
    let analyser = null;
    if (currentOrbState === 'speaking') {
      analyser = remoteAnalyser;
    } else if (currentOrbState === 'listening') {
      analyser = localAnalyser;
    }
    
    if (!analyser) return 0;
    
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(dataArray);
    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) {
      sum += dataArray[i];
    }
    return sum / dataArray.length / 255; // Normalized value between 0 and 1
  }

  // --- FastAPI Authentication (JWT) ---
