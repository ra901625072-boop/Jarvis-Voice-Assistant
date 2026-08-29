# UI Design Rules & Modern Frontend Standards

Master guidelines for UI design, spatial architecture, typography scales, color token systems, component state matrices, and motion dynamics.

---

## 1. Anti-Generic "No-Slop" Principles
AI-generated interfaces must avoid cookie-cutter cliches (e.g. flat purple gradients, identical cards, generic typography). Follow these core aesthetic principles:
1. **Atmosphere & Depth**: Combine glassmorphism (`backdrop-filter: blur(16px)`), subtle inner borders (`1px solid rgba(255,255,255,0.08)`), and multi-layered elevation shadows rather than single flat surfaces.
2. **Distinctive Typography**: Pair bold characterful display headings (*Plus Jakarta Sans, Syne, Cabinet Grotesk, Clash Display*) with ultra-clean, readable body text (*Inter, Outfit, Geist*).
3. **Intentional Spatial Composition**: Avoid wall-to-wall repetitive grids. Use asymmetrical hero cards, floating status pills, and purposeful negative space (whitespace) to guide user focus.

---

## 2. 4pt / 8pt Spatial Scale & Layout Grids
All spacing, component heights, gaps, margins, and padding MUST strictly derive from an incremental 4px/8px scale:

| Token | Size (px) | Size (rem) | Usage |
| :--- | :--- | :--- | :--- |
| `--space-xs` | 4px | 0.25rem | Icon spacing, tight badge padding |
| `--space-sm` | 8px | 0.5rem | Small button padding, form input inline gaps |
| `--space-md` | 16px | 1.0rem | Card internal padding, standard form field spacing |
| `--space-lg` | 24px | 1.5rem | Grid gaps, card separators, section margins |
| `--space-xl` | 32px | 2.0rem | Section headers, modal internal padding |
| `--space-2xl` | 48px | 3.0rem | Major layout blocks, hero banners |
| `--space-3xl` | 64px | 4.0rem | Page section vertical spacing |

- **Touch Target Ergonomics**: Any interactive element (button, link, toggle, icon trigger) MUST have a minimum tap target of **44x44px** on mobile viewports.
- **Fluid Layouts**: Use CSS `clamp()` and `minmax()` for responsive scaling across breakpoints (Desktop: 1200px+, Tablet: 768px–1199px, Mobile: < 768px).

---

## 3. Color Token Hierarchy & Contrast Standards (WCAG 2.2 AA / AAA)
- **60-30-10 Distribution**:
  - **60% Dominant Base**: Deep background surface (`--bg-body`, `--bg-card`).
  - **30% Secondary Structure**: Surface borders, text secondary, subtle dividers (`--border`, `--text-secondary`).
  - **10% Accent / Brand**: High-impact CTA buttons, active indicators, notification badges (`--primary`, `--accent`).
- **Mathematical Contrast Ratios**:
  - **Normal Text (< 18pt / 24px)**: Contrast ratio $\ge 4.5:1$ (WCAG AA) and $\ge 7.0:1$ (WCAG AAA).
  - **Large Text ($\ge 18\text{pt}$ / bold $14\text{pt}$)** & UI Components: Ratio $\ge 3.0:1$ (WCAG AA) and $\ge 4.5:1$ (WCAG AAA).
  - Never use light gray text (e.g. `#999999` or `#A0AEC0`) on white backgrounds.
- **Dual-Token System**: Every color token MUST support dark/light mappings via CSS custom properties:
  ```css
  :root, [data-theme="light"] {
    --bg-body: #F8FAFC;
    --bg-card: #FFFFFF;
    --text-primary: #0F172A;
    --text-secondary: #475569;
    --primary: #4F46E5;
    --primary-hover: #4338CA;
    --border: #E2E8F0;
  }
  [data-theme="dark"] {
    --bg-body: #0B0F19;
    --bg-card: #131B2E;
    --text-primary: #F8FAFC;
    --text-secondary: #CBD5E1;
    --primary: #6366F1;
    --primary-hover: #4F46E5;
    --border: #1E293B;
  }
  ```

---

## 4. The 6 Mandatory Component Interactive States
Every interactive component (buttons, inputs, cards, selects) MUST implement all 6 states:

1. **Default**: Resting state with clear affordance and readable typography.
2. **Hover**: Subtle elevation (`transform: translateY(-2px); box-shadow: var(--shadow-md);`), background color shift with `transition: 0.2s ease`.
3. **Focus-Visible**: High-contrast outline with offset (`:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }`). Never use `outline: none` without providing an accessible alternative.
4. **Active / Pressed**: Subtle scale reduction (`transform: scale(0.98);`), darker background shade on mousedown/tap.
5. **Disabled**: Reduced opacity (0.5), `cursor: not-allowed;`, `aria-disabled="true"`, non-submitting.
6. **Loading**: Visual spinner or skeleton shimmer, `aria-busy="true"`, preventing duplicate actions.

---

## 5. Micro-Interactions, Motion Curves & Accessibility
- **Fast Feedback (Buttons, Tabs, Badges)**: `150ms – 200ms ease-out`.
- **Structural Shifts (Modals, Drawers, Accordions)**: `300ms – 350ms cubic-bezier(0.16, 1, 0.3, 1)`.
- **Reduced Motion Support**:
  ```css
  @media (prefers-reduced-motion: reduce) {
    *, ::before, ::after {
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
      scroll-behavior: auto !important;
    }
  }
  ```
