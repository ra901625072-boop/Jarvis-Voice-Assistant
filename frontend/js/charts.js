// charts.js — Render beautiful Chart.js reports inside Analytics tab

class MetricsCharts {
    constructor() {
        this.tasksChart = null;
        this.perfChart = null;
        this.jwtToken = null;
        this.apiKey = null;
        this.cpuHistory = Array(10).fill(0);
        this.tempHistory = Array(10).fill(0);
        this.labels = Array(10).fill('');
        this.pollInterval = null;
    }

    setAuth(apiKey, jwtToken) {
        this.apiKey = apiKey;
        this.jwtToken = jwtToken;

        this.initCharts();
        this.fetchMetrics();
        
        if (this.pollInterval) clearInterval(this.pollInterval);
        this.pollInterval = setInterval(() => this.fetchMetrics(), 4000);
    }

    initCharts() {
        const tasksCtx = document.getElementById('tasks-chart');
        const perfCtx = document.getElementById('performance-chart');

        if (tasksCtx && !this.tasksChart) {
            this.tasksChart = new Chart(tasksCtx, {
                type: 'bar',
                data: {
                    labels: ['Completed', 'Failed', 'Queued', 'Cancelled'],
                    datasets: [{
                        label: 'Tasks Executed Today',
                        data: [0, 0, 0, 0],
                        backgroundColor: [
                            'rgba(16, 185, 129, 0.4)', // green
                            'rgba(239, 68, 68, 0.4)',  // red
                            'rgba(255, 157, 0, 0.4)',  // yellow
                            'rgba(100, 116, 139, 0.4)'  // gray
                        ],
                        borderColor: [
                            '#10b981',
                            '#ef4444',
                            '#ff9d00',
                            '#64748b'
                        ],
                        borderWidth: 1.5
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { labels: { color: '#ecfeff', font: { family: 'Rajdhani' } } }
                    },
                    scales: {
                        x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#ecfeff', font: { family: 'Rajdhani' } } },
                        y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#ecfeff', font: { family: 'Rajdhani' } } }
                    }
                }
            });
        }

        if (perfCtx && !this.perfChart) {
            this.perfChart = new Chart(perfCtx, {
                type: 'line',
                data: {
                    labels: this.labels,
                    datasets: [
                        {
                            label: 'CPU Load (%)',
                            data: this.cpuHistory,
                            borderColor: '#00d4ff',
                            backgroundColor: 'rgba(0, 212, 255, 0.05)',
                            fill: true,
                            tension: 0.4
                        },
                        {
                            label: 'Core Temp (°C)',
                            data: this.tempHistory,
                            borderColor: '#ff9d00',
                            backgroundColor: 'rgba(255, 157, 0, 0.05)',
                            fill: true,
                            tension: 0.4
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { labels: { color: '#ecfeff', font: { family: 'Rajdhani' } } }
                    },
                    scales: {
                        x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#ecfeff', font: { family: 'Rajdhani' } } },
                        y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#ecfeff', font: { family: 'Rajdhani' } } }
                    }
                }
            });
        }
    }

    async fetchMetrics() {
        if (!this.jwtToken) return;

        try {
            // Fetch stats
            const statsRes = await fetch('http://localhost:8001/api/stats', {
                headers: { 'Authorization': `Bearer ${this.jwtToken}` }
            });
            if (statsRes.ok) {
                const stats = await statsRes.json();
                this.updatePerformanceData(stats.cpu, stats.temp || 0);
            }

            // Fetch tasks stats
            const tasksRes = await fetch('http://localhost:8001/api/tasks', {
                headers: { 'Authorization': `Bearer ${this.jwtToken}` }
            });
            if (tasksRes.ok) {
                const data = await tasksRes.json();
                this.updateTasksChart(data.tasks);
            }
        } catch (e) {
            console.error("Failed to load metrics data:", e);
        }
    }

    updatePerformanceData(cpu, temp) {
        if (!this.perfChart) return;

        // Push new data and shift
        this.cpuHistory.push(Math.round(cpu));
        this.cpuHistory.shift();

        this.tempHistory.push(Math.round(temp));
        this.tempHistory.shift();

        const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        this.labels.push(timeStr);
        this.labels.shift();

        this.perfChart.data.labels = this.labels;
        this.perfChart.data.datasets[0].data = this.cpuHistory;
        this.perfChart.data.datasets[1].data = this.tempHistory;
        this.perfChart.update('none');
    }

    updateTasksChart(tasks) {
        if (!this.tasksChart || !tasks) return;

        let completed = 0, failed = 0, queued = 0, cancelled = 0;
        tasks.forEach(t => {
            const status = t.status;
            if (status === 'completed') completed++;
            else if (status === 'failed') failed++;
            else if (status === 'queued' || status === 'running') queued++;
            else if (status === 'cancelled') cancelled++;
        });

        this.tasksChart.data.datasets[0].data = [completed, failed, queued, cancelled];
        this.tasksChart.update();
    }

    cleanup() {
        if (this.pollInterval) clearInterval(this.pollInterval);
    }
}
