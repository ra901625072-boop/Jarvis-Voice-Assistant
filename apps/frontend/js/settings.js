  function setupDragDropZone(zone, fileInput, onFileSelected) {
    zone.addEventListener('click', () => fileInput.click());
    
    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('dragover');
    });
    
    zone.addEventListener('dragleave', () => {
      zone.classList.remove('dragover');
    });
    
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('dragover');
      if (e.dataTransfer.files.length > 0) {
        onFileSelected(e.dataTransfer.files[0]);
      }
    });
    
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length > 0) {
        onFileSelected(fileInput.files[0]);
      }
    });
  }

  function handleCustomSkillFile(file) {
    if (!file.name.endsWith('.md') && !file.name.endsWith('.markdown')) {
      alert("Only .md or .markdown extension files are accepted.");
      return;
    }
    
    const reader = new FileReader();
    reader.onload = async () => {
      const text = reader.result;
      currentUploadedSkillMd = text;
      
      try {
        const valRes = await fetch(`${apiBase}/api/skills/validate-md`, {
          method: 'POST',
          headers: getHeaders(),
          body: JSON.stringify({ raw_markdown: text })
        });
        const valData = await valRes.json();
        if (!valRes.ok) {
          throw new Error(valData.detail || valData.message || 'Validation request failed with status ' + valRes.status);
        }
        
        skillMdPreviewPanel.classList.remove('hidden');
        if (valData.valid) {
          skillMdPreviewName.textContent = valData.metadata.name || "-";
          skillMdPreviewDesc.textContent = valData.metadata.description || "-";
          skillMdPreviewCategory.textContent = valData.metadata.category || "custom";
          const triggers = valData.metadata.trigger;
          skillMdPreviewTriggers.textContent = Array.isArray(triggers) ? triggers.join(', ') : (triggers || "-");
          
          skillMdErrorMsg.classList.add('hidden');
          btnDeployMdSkill.removeAttribute('disabled');
        } else {
          skillMdPreviewName.textContent = "-";
          skillMdPreviewDesc.textContent = "-";
          skillMdPreviewCategory.textContent = "-";
          skillMdPreviewTriggers.textContent = "-";
          
          const errors = valData.errors || [];
          skillMdErrorMsg.textContent = errors.length > 0 ? errors.join('\n') : 'Invalid markdown file.';
          skillMdErrorMsg.classList.remove('hidden');
          btnDeployMdSkill.setAttribute('disabled', 'true');
        }
      } catch (err) {
        skillMdErrorMsg.textContent = "Error communicating with validation server: " + err.message;
        skillMdErrorMsg.classList.remove('hidden');
        btnDeployMdSkill.setAttribute('disabled', 'true');
      }
    };
    reader.readAsText(file);
  }

  function handleWorkflowMdFile(file) {
    if (!file.name.endsWith('.md') && !file.name.endsWith('.markdown')) {
      alert("Only .md or .markdown extension files are accepted.");
      return;
    }
    
    const reader = new FileReader();
    reader.onload = async () => {
      const text = reader.result;
      currentUploadedWorkflowMd = text;
      
      try {
        const valRes = await fetch(`${apiBase}/api/workflows/validate-md`, {
          method: 'POST',
          headers: getHeaders(),
          body: JSON.stringify({ raw_markdown: text })
        });
        const valData = await valRes.json();
        
        if (!valRes.ok) {
          throw new Error(valData.detail || valData.message || 'Validation request failed with status ' + valRes.status);
        }
        
        workflowMdPreviewPanel.classList.remove('hidden');
        if (valData.valid) {
          wfMdPreviewName.textContent = valData.metadata.name || "-";
          wfMdPreviewDesc.textContent = valData.metadata.description || "-";
          wfMdPreviewSchedule.textContent = valData.metadata.schedule || "None (Run-on-demand)";
          
          if (valData.steps && valData.steps.length > 0) {
            wfMdPreviewStepsBody.innerHTML = valData.steps.map((st, idx) => {
              const escAgent = typeof escapeHtml === 'function' ? escapeHtml(st.agent) : st.agent;
              const escAction = typeof escapeHtml === 'function' ? escapeHtml(st.action) : st.action;
              const payloadStr = JSON.stringify(st.payload || {});
              const escPayload = typeof escapeHtml === 'function' ? escapeHtml(payloadStr) : payloadStr;
              return `
              <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 0.8rem;">
                <td style="padding: 0.4rem 0.25rem; font-weight: bold; color: rgba(255,255,255,0.5);">${idx + 1}</td>
                <td style="padding: 0.4rem 0.25rem;">${escAgent}</td>
                <td style="padding: 0.4rem 0.25rem; font-family: monospace; color: #a5d6ff;">${escAction}</td>
                <td style="padding: 0.4rem 0.25rem; font-family: monospace; color: #85e89d; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escPayload}">${escPayload}</td>
              </tr>
            `;}).join('');
          } else {
            wfMdPreviewStepsBody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 0.5rem; color: rgba(255,255,255,0.5);">No steps found</td></tr>';
          }
          
          workflowMdErrorMsg.classList.add('hidden');
          btnDeployMdWorkflow.removeAttribute('disabled');
        } else {
          wfMdPreviewName.textContent = "-";
          wfMdPreviewDesc.textContent = "-";
          wfMdPreviewSchedule.textContent = "-";
          wfMdPreviewStepsBody.innerHTML = "";
          
          const errors = valData.errors || [];
          const escHelper = typeof escapeHtml === 'function' ? escapeHtml : (s => s);
          workflowMdErrorMsg.innerHTML = errors.length > 0 ? errors.map(err => `<div>${escHelper(err)}</div>`).join('') : 'Invalid markdown file.';
          workflowMdErrorMsg.classList.remove('hidden');
          btnDeployMdWorkflow.setAttribute('disabled', 'true');
        }
      } catch (err) {
        workflowMdErrorMsg.textContent = "Error communicating with validation server: " + err.message;
        workflowMdErrorMsg.classList.remove('hidden');
        btnDeployMdWorkflow.setAttribute('disabled', 'true');
      }
    };
    reader.readAsText(file);
  }

