// workflow_builder.js — Drag-and-drop agent pipeline compiler

class WorkflowBuilder {
    constructor() {
        this.canvas = document.getElementById('workflow-canvas-steps');
        this.saveBtn = document.getElementById('save-workflow-btn');
        this.dragSteps = document.querySelectorAll('.drag-step');
        this.steps = [];
        this.jwtToken = null;
        this.apiKey = null;

        this.initEvents();
    }

    setAuth(apiKey, jwtToken) {
        this.apiKey = apiKey;
        this.jwtToken = jwtToken;
    }

    initEvents() {
        if (!this.canvas) return;

        // Drag events on toolbox
        this.dragSteps.forEach(step => {
            step.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', e.target.getAttribute('data-action'));
                e.dataTransfer.setData('text/label', e.target.innerText);
            });
        });

        // Drag events on canvas
        this.canvas.addEventListener('dragover', (e) => {
            e.preventDefault();
        });

        this.canvas.addEventListener('drop', (e) => {
            e.preventDefault();
            const action = e.dataTransfer.getData('text/plain');
            const label = e.dataTransfer.getData('text/label');
            if (action && label) {
                this.addStep(action, label);
            }
        });

        if (this.saveBtn) {
            this.saveBtn.addEventListener('click', () => this.saveAndRunWorkflow());
        }
    }

    addStep(action, label) {
        // Remove empty placeholder if first step
        const placeholder = this.canvas.querySelector('.canvas-empty');
        if (placeholder) placeholder.remove();

        const stepId = `step_${Date.now()}`;
        this.steps.push({ id: stepId, action, label });

        const stepItem = document.createElement('div');
        stepItem.className = 'canvas-step-item';
        stepItem.setAttribute('data-id', stepId);
        stepItem.innerHTML = `
            <span>${label} (${action})</span>
            <span class="remove-step">&times;</span>
        `;

        stepItem.querySelector('.remove-step').addEventListener('click', () => {
            this.removeStep(stepId, stepItem);
        });

        this.canvas.appendChild(stepItem);
    }

    removeStep(stepId, element) {
        this.steps = this.steps.filter(s => s.id !== stepId);
        element.remove();

        if (this.steps.length === 0) {
            this.canvas.innerHTML = '<div class="canvas-empty">Drag steps here to build pipeline</div>';
        }
    }

    async saveAndRunWorkflow() {
        if (this.steps.length === 0) {
            alert("Please add at least one step to the pipeline.");
            return;
        }

        const name = `Workflow Pipeline ${new Date().toLocaleTimeString()}`;
        
        try {
            const token = this.jwtToken;
            if (!token) return;

            // Save workflow
            const saveResponse = await fetch('http://localhost:8001/api/workflows', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    name: name,
                    steps: this.steps.map(s => ({ action: s.action, label: s.label }))
                })
            });

            if (saveResponse.ok) {
                const data = await saveResponse.json();
                const wfId = data.workflow.id;
                
                // Trigger execution immediately
                const runResponse = await fetch(`http://localhost:8001/api/workflows/${wfId}/run`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });

                if (runResponse.ok) {
                    alert("Workflow pipeline compiles and launched successfully! Check the task feed.");
                    
                    // Switch back to HUD tab
                    document.getElementById('tab-hud').click();
                    
                    // Clear canvas
                    this.steps = [];
                    this.canvas.innerHTML = '<div class="canvas-empty">Drag steps here to build pipeline</div>';
                }
            }
        } catch (e) {
            console.error("Failed to compile and run workflow pipeline:", e);
        }
    }
}
