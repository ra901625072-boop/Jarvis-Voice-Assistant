// agent_status.js — Polls FastAPI for agent (toolset/skill) busy states

class AgentStatusManager {
    constructor() {
        this.container = document.getElementById('agent-grid-container');
        this.jwtToken = null;
        this.apiKey = null;
        this.interval = null;
    }

    setAuth(apiKey, jwtToken) {
        this.apiKey = apiKey;
        this.jwtToken = jwtToken;
        
        // Start polling loop
        if (this.interval) clearInterval(this.interval);
        this.fetchAgentStatuses();
        this.interval = setInterval(() => this.fetchAgentStatuses(), 4000);
    }

    async fetchAgentStatuses() {
        if (!this.container) return;
        
        try {
            const token = this.jwtToken;
            if (!token) return;

            const response = await fetch('http://localhost:8001/api/agents', {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (response.ok) {
                const data = await response.json();
                this.renderAgents(data.agents);
            }
        } catch (e) {
            console.error("Failed to fetch agent statuses:", e);
        }
    }

    renderAgents(agents) {
        if (!this.container || !agents) return;
        this.container.innerHTML = '';

        agents.forEach(agent => {
            const card = document.createElement('div');
            card.className = `agent-card ${agent.status === 'busy' ? 'busy' : ''}`;
            
            // Clean up name by removing 'Tools' or 'Skill' suffix for cleaner HUD aesthetic
            let shortName = agent.name.replace('Tools', '').replace('Skill', '');
            if (shortName.length > 12) shortName = shortName.substring(0, 10) + '..';

            card.title = `${agent.name}: ${agent.description}`;
            card.innerHTML = `
                <span>${this.escapeHtml(shortName)}</span>
                <span class="status-dot"></span>
            `;
            this.container.appendChild(card);
        });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.innerText = text;
        return div.innerHTML;
    }
}
