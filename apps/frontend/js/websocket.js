  function connectTasksWebSocket() {
    if (tasksSocket) {
      tasksSocket.close();
    }
    
    const wsUrl = `${wsBase}/api/ws/tasks`;
    tasksSocket = new WebSocket(wsUrl);
    
    tasksSocket.onopen = () => {
      console.log('Global tasks WebSocket connected.');
    };
    
    tasksSocket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === 'init' || message.type === 'update') {
          renderTasksList(message.tasks);
        } else if (message.type === 'APPROVAL_REQUIRED') {
          alert(`[AUTHORIZATION REQUIRED] ${message.message}`);
          loadApprovals(); // Reload list
        }
      } catch (e) {
        console.error('Failed parsing WebSocket JSON:', e);
      }
    };
    
    tasksSocket.onclose = () => {
      console.log('Tasks WebSocket disconnected. Reconnecting in 3s...');
      setTimeout(() => {
        if (jwtToken) connectTasksWebSocket();
      }, 3000);
    };
  }

  // --- Tasks API Actions ---
