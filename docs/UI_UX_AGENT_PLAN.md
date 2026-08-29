# UI/UX Agent Plan & Architecture Specification

## Overview

The `ui_ux_agent` is JARVIS's specialist product and interface design agent. It combines design theory (Nielsen heuristics, WCAG 2.2 AA, Gestalt principles) with code-aware component specs and design token generation.

---

## 1. Model Routing & Fallback Chain

The model chain is optimized for screenshot-to-UI visual reasoning, design token extraction, and frontend component generation:

```
Primary: Kimi K2.5 (`moonshotai/kimi-k2.5` via OpenRouter / Self-Hosted)
   │
   ▼ (Fallback if rate limited or unconfigured)
Secondary: Gemini 3.6 / 2.5 Flash (`gemini-2.5-flash` / `gemini-3.6-flash`)
   │
   ▼ (Fallback for code generation)
Tertiary: DeepSeek V3 / Qwen 2.5 Coder
```

### Rationale

1. **Kimi K2.5 (Primary)**:
   - Open-weights architecture under modified MIT license (can be self-hosted for free).
   - Native multimodal architecture excels at analyzing UI screenshots and generating matching code.
   - Cost-effective (~5x cheaper than Claude Sonnet per million tokens via OpenRouter).

2. **Gemini 3.6 / 2.5 Flash (Fallback)**:
   - Available on Google AI Studio free tier.
   - Extremely reliable structured JSON generation and high speed.

3. **Claude Sonnet 4.6 (Optional Premium Tier)**:
   - Configurable via `JARVIS_OPENROUTER_MODEL_UI_UX=anthropic/claude-3.5-sonnet` when high-complexity design system reasoning is required.

---

## 2. Configuration Settings (`config/settings.py`)

- **Timeout**: 300 seconds (`AGENT_TIMEOUTS["ui_ux_agent"] = 300.0`)
- **OpenRouter Route**: `OPENROUTER_MODEL_MAP["ui_ux_agent"] = os.environ.get("JARVIS_OPENROUTER_MODEL_UI_UX", "moonshotai/kimi-k2.5")`

---

## 3. Core Task Capabilities

| Task Type | Description | Primary Output Format |
|-----------|-------------|-----------------------|
| `design_review` | Critique UI layout, visual hierarchy, heuristics | Structured JSON (Usability, Accessibility, Recommendations) |
| `audit_accessibility` | WCAG 2.2 AA compliance audit | Severity-ranked JSON issues list |
| `generate_wireframe` | Layout & Information Architecture spec | Mobile-first component hierarchy |
| `generate_hifi_spec` | Full visual specification | Typography, color hex, spacing scale, component states |
| `generate_design_tokens` | Code-ready token scales | CSS Custom Properties (`:root`), Tailwind / shadcn/ui mappings |
| `design_research` | Industry pattern analysis & references | Curated design patterns with accessibility notes |

---

## 4. Integration into JARVIS Swarm

- **Bus Registration**: Registered as `ui_ux_agent` on `AgentBus` (priority 49.8).
- **Coordinator Routing**: Triggered for queries containing keywords: `design`, `wireframe`, `UI`, `UX`, `color palette`, `accessibility`, `WCAG`, `redesign`, `design tokens`.
- **Brain Integration**: Dynamically loads `persona.md`, `knowledge_base.md`, and `tooling_landscape.md` from `ai/agents/ui_ux/brain/`.
