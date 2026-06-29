// task_manager.js — Handles WS tasks feed + submission of text commands

class TaskFeedManager {
    constructor() {
        this.container = document.getElementById('task-feed-container');
        this.commandInput = document.getElementById('text-command-input');
        this.sendBtn = document.getElementById('send-command-btn');
        this.socket = null;
        this.jwtToken = null;
        this.apiKey = null;
        this.reconnectAttempts = 0;
        
        this.initEvents();
    }

    setAuth(apiKey, jwtToken) {
        this.apiKey = apiKey;
        this.jwtToken = jwtToken;
        this.connectWebSocket();
    }

    initEvents() {
        if (this.sendBtn && this.commandInput) {
            this.sendBtn.addEventListener('click', () => this.submitCommand());
            this.commandInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.submitCommand();
            });
        }
    }

    async submitCommand() {
        const cmd = this.commandInput.value.trim();
        if (!cmd) return;

        this.commandInput.value = '';
        this.commandInput.disabled = true;
        this.sendBtn.disabled = true;

        try {
            const token = this.jwtToken || await this.getJWTToken(this.apiKey);
            const response = await fetch('http://localhost:8001/api/tasks', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({ input: cmd, priority: 'normal' })
            });

            if (!response.ok) {
                console.error("Failed to submit task:", await response.text());
            }
        } catch (e) {
            console.error("Error submitting text command:", e);
        } finally {
            this.commandInput.disabled = false;
            this.sendBtn.disabled = false;
            this.commandInput.focus();
        }
    }

    async getJWTToken(apiKey) {
        if (!apiKey) return null;
        try {
            const response = await fetch('http://localhost:8001/api/auth/token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: apiKey })
            });
            if (response.ok) {
                const data = await response.json();
                this.jwtToken = data.token;
                return data.token;
            }
        } catch (e) {
            console.error("Failed to fetch JWT token:", e);
        }
        return null;
    }

    connectWebSocket() {
        if (this.socket) {
            try { this.socket.close(); } catch(e) {}
        }

        const wsUrl = `ws://localhost:8001/api/ws/tasks`;
        console.log("Connecting tasks WebSocket to:", wsUrl);
        this.socket = new WebSocket(wsUrl);

        this.socket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'init' || data.type === 'update') {
                    this.renderTasks(data.tasks);
                }
            } catch (e) {
                console.error("Failed to parse task WS update:", e);
            }
        };

        this.socket.onclose = () => {
            console.warn("Tasks WebSocket closed. Attempting reconnect...");
            if (this.reconnectAttempts < 10) {
                this.reconnectAttempts++;
                setTimeout(() => this.connectWebSocket(), 3000);
            }
        };

        this.socket.onerror = (e) => {
            console.error("Tasks WebSocket error:", e);
        };
    }

    renderTasks(tasks) {
        if (!this.container) return;

        if (!tasks || tasks.length === 0) {
            this.container.innerHTML = '<p class="empty-feed-text">No active directives</p>';
            return;
        }

        this.container.innerHTML = '';
        
        // Take the 5 most recent tasks to prevent cluttering the UI
        tasks.slice(0, 5).forEach(task => {
            const item = document.createElement('div');
            item.className = 'task-item';

            const status = task.status || 'queued';
            const progress = task.progress !== undefined ? task.progress : 0;
            const displayTitle = task.kwargs && task.kwargs.input ? task.kwargs.input : (task.task_type || 'System Task');

            item.innerHTML = `
                <div class="task-item-header">
                    <div class="task-item-title">${this.escapeHtml(displayTitle)}</div>
                    <div class="task-item-status ${status}">${status}</div>
                </div>
                <div class="task-progress-bar">
                    <div class="task-progress-fill" style="width: ${progress}%"></div>
                </div>
            `;
            this.container.appendChild(item);
        });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.innerText = text;
        return div.innerHTML;
    }
}
