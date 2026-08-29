/**
 * JARVIS Workflow DAG Renderer
 * Builds an inline SVG directed graph (User -> step 1 -> step 2 -> ... -> Answer)
 * for a workflow definition, with optional per-step status coloring.
 * Pure function, no DOM globals required — returns an SVG string.
 */

(function () {
  const NODE_W = 168;
  const NODE_H = 56;
  const GAP_X = 64;
  const PAD = 32;

  function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function statusColor(status) {
    switch ((status || '').toLowerCase()) {
      case 'running': return { stroke: 'var(--c-primary)', fill: 'var(--c-primary-glow)', text: 'var(--c-primary)' };
      case 'completed':
      case 'done': return { stroke: 'var(--c-success)', fill: 'var(--c-success-glow)', text: 'var(--c-success)' };
      case 'failed':
      case 'error': return { stroke: 'var(--c-danger)', fill: 'var(--c-danger-glow)', text: 'var(--c-danger)' };
      case 'waiting':
      case 'queued': return { stroke: 'var(--c-warning)', fill: 'var(--c-warning-glow)', text: 'var(--c-warning)' };
      default: return { stroke: 'rgba(255,255,255,0.18)', fill: 'rgba(255,255,255,0.03)', text: 'rgba(255,255,255,0.55)' };
    }
  }

  /**
   * @param {Object} workflow - { steps: [{ name, agent, action, status }], status }
   * @returns {string} SVG markup string (viewBox-scaled, meant to be dropped into a scrollable-x container)
   */
  function buildWorkflowDagSvg(workflow) {
    const steps = (workflow && workflow.steps) || [];
    const nodes = [
      { label: 'User', sub: 'trigger', kind: 'endpoint', status: 'completed' },
      ...steps.map((s) => ({
        label: s.name || s.action || 'Step',
        sub: (s.agent || 'agent').replace(/_agent$/i, ''),
        kind: 'step',
        status: s.status || workflow.__inferredStatus || null
      })),
      { label: 'Answer', sub: 'output', kind: 'endpoint', status: null }
    ];

    const totalW = PAD * 2 + nodes.length * NODE_W + (nodes.length - 1) * GAP_X;
    const totalH = PAD * 2 + NODE_H;
    const centerY = PAD + NODE_H / 2;

    let edgesSvg = '';
    let nodesSvg = '';

    nodes.forEach((node, i) => {
      const x = PAD + i * (NODE_W + GAP_X);
      const colors = statusColor(node.status);
      const isEndpoint = node.kind === 'endpoint';

      if (i > 0) {
        const prevX = PAD + (i - 1) * (NODE_W + GAP_X) + NODE_W;
        const midX = (prevX + x) / 2;
        edgesSvg += `
          <line x1="${prevX}" y1="${centerY}" x2="${x - 10}" y2="${centerY}"
                stroke="rgba(255,255,255,0.18)" stroke-width="2" marker-end="url(#dagArrow)" />
          ${node.status === 'running' ? `<circle cx="${midX}" cy="${centerY}" r="3" fill="var(--c-primary)"><animate attributeName="cx" from="${prevX}" to="${x}" dur="1.4s" repeatCount="indefinite" /></circle>` : ''}
        `;
      }

      nodesSvg += `
        <g class="dag-node" data-step-index="${i}">
          <rect x="${x}" y="${PAD}" width="${NODE_W}" height="${NODE_H}" rx="10"
                fill="${colors.fill}" stroke="${colors.stroke}" stroke-width="1.5" />
          <text x="${x + 14}" y="${PAD + 22}" font-size="12.5" font-weight="600"
                fill="#fff" font-family="var(--font-body)">${escapeHtml(node.label.length > 18 ? node.label.slice(0, 17) + '…' : node.label)}</text>
          <text x="${x + 14}" y="${PAD + 38}" font-size="10.5" letter-spacing="0.5"
                fill="${colors.text}" font-family="var(--font-mono)">${isEndpoint ? node.sub.toUpperCase() : escapeHtml(node.sub).toUpperCase()}</text>
        </g>
      `;
    });

    return `
      <svg viewBox="0 0 ${totalW} ${totalH}" width="${totalW}" height="${totalH}" xmlns="http://www.w3.org/2000/svg" class="dag-svg">
        <defs>
          <marker id="dagArrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L0,6 L6,3 z" fill="rgba(255,255,255,0.3)" />
          </marker>
        </defs>
        ${edgesSvg}
        ${nodesSvg}
      </svg>
    `;
  }

  window.buildWorkflowDagSvg = buildWorkflowDagSvg;
})();
