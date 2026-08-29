# UI/UX Tooling Landscape — Design Tools & Frontend Libraries

Two buckets: the design/prototyping tools and the code libraries you
ship with. Worth knowing both for full-stack work.

---

## Design & Prototyping Tools

### Core Tools

| Tool | Role | Key Strength |
|------|------|-------------|
| **Figma** | Default all-in-one | Whiteboarding → wireframes → hi-fi → dev handoff in one place, FigJam built in, real-time collaboration |
| **Framer** | Advanced prototyping | Interactive prototypes that hand off close to production-ready |
| **Sketch** | Mac-native design | 2025 rewrite restored native macOS feel; symbol libraries scale better than Figma components on huge projects |
| **UXPin / Axure** | Logic-heavy prototyping | Data-driven prototypes with real state, conditional flows, form logic |

### Research & Inspiration Sources

| Source | Use |
|--------|-----|
| **Mobbin** | Current UI patterns and real product flows — best for studying existing solutions before designing |
| **Dribbble** | Visual inspiration and trending UI styles — best for exploring visual direction |
| **Behance** | Full case studies with process documentation |
| **Awwwards** | Award-winning web design — best for cutting-edge interaction patterns |

### AI-Assisted Design (2025–2026)

- **Figma AI** — layout and component generation inside Figma itself
- **Lovable** — description → fully editable, production-ready UI that pastes into Figma
- These tools augment, not replace, the design process — they speed up
  the wireframe→hi-fi transition but still need designer review against
  heuristics and accessibility standards

---

## Frontend Component Libraries

### For React + Tailwind Stack (recommended pairing)

| Library | Best For | Notes |
|---------|----------|-------|
| **shadcn/ui** | Most new React projects (2026 top pick) | Tailwind-native, copy-paste components, zero runtime. Source code lives in YOUR repo — full ownership, not a dependency |
| **Base UI** | Unstyled primitives | Emerged from MUI team as actively-maintained primitive layer after Radix UI development slowed (WorkOS acquisition). shadcn/ui now supports Radix OR Base UI underneath |
| **daisyUI** | Fast prototyping | Semantic class names (`btn`, `card`, `modal`) on top of Tailwind — skip building components from scratch |

### Enterprise / Data-Heavy

| Library | Best For | Notes |
|---------|----------|-------|
| **MUI (Material UI)** | Enterprise apps | Large component set, strong theming — budget time for customization |
| **Ant Design** | Admin dashboards, complex data tables | Strong for data-dense UIs — particularly admin panels |
| **Tremor** | Dashboards / analytics | Tailwind-based, purpose-built for KPI cards, charts, stats views |

### Recommended Stack Pairing

**Design pass:** Figma + FigJam
**Build pass:** shadcn/ui + Tailwind CSS

This is the pairing most indie/solo devs converge on in 2026. It fits
the frontend-design conventions already established in this environment.

---

## Tool Selection Decision Tree

```
Is this a design/research task?
├── Yes → Figma (default) or Framer (if interactive prototype needed)
│         Use Mobbin/Dribbble for reference BEFORE designing
│
└── No, it's a build task →
    ├── New React project? → shadcn/ui + Tailwind
    ├── Enterprise/data-heavy? → MUI or Ant Design
    ├── Dashboard/analytics? → Tremor
    └── Quick prototype? → daisyUI + Tailwind
```

## When to Recommend Each Tool in Agent Responses

- Default recommendation: **Figma** for design, **shadcn/ui** for build
- Only recommend Sketch if user specifies Mac-only workflow
- Only recommend UXPin/Axure for complex form/state prototypes
- Always suggest checking Mobbin/Dribbble BEFORE starting visual design
- When suggesting a component library, note whether it's a dependency
  (MUI, Ant) or owned source (shadcn/ui) — this affects long-term
  maintenance cost
