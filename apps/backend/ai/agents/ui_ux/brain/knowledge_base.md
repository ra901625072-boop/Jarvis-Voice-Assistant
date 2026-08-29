# UI/UX Designer — Necessary Knowledge & Skills

A practical roadmap of what's actually required, organized by the same
six domains from the mindmap, plus the pieces that mindmap
leaves out (soft skills, dev-handoff, portfolio). Checklist format so you
can track it directly.

---

## 1. Design Foundations (the theory everything else sits on)

- [ ] **Typography** — type pairing, hierarchy (H1→body→caption scale),
      line-height/letter-spacing rules, readable line length (~50–75 chars)
- [ ] **Color theory** — contrast ratios (WCAG AA: 4.5:1 body text), color
      as hierarchy/state signal (not just decoration), light/dark mode pairs
- [ ] **Layout & grid systems** — 8pt spacing grid, 12-column responsive
      grid, alignment, whitespace as a design tool not "empty space"
- [ ] **Gestalt principles** — proximity, similarity, continuity, figure/
      ground — why your eye reads a screen the way it does
- [ ] **Design psychology** — Hick's Law (more choices = slower decisions),
      Fitts's Law (target size/distance), cognitive load, visual hierarchy
- [ ] **Accessibility basics** — WCAG 2.2 AA: contrast, focus order, tap
      target size (min 44×44px), motion-reduction, screen-reader labeling

## 2. UX Process (how you get from "problem" to "screen")

- [ ] **User research** — interviews, surveys, competitive analysis; enough
      to write a persona that isn't a guess
- [ ] **Information architecture** — sitemaps, card sorting, navigation
      structure — the skeleton before any screen exists
- [ ] **User flows** — mapping the path a user takes to complete one task,
      not just what a screen looks like in isolation
- [ ] **Wireframing (low-fi)** — structure only, no color/type, forces you
      to solve layout before you get distracted by visual polish
- [ ] **Usability testing** — heuristic evaluation (Nielsen's 10) at
      minimum; moderated user testing when you have real users to test with

## 3. UI Design (the visible craft)

- [ ] **High-fidelity visual design** — applying real type/color/spacing to
      a validated wireframe, not skipping straight here
- [ ] **Design systems / component libraries** — reusable buttons, inputs,
      cards, modals with consistent states (default/hover/active/disabled)
- [ ] **Responsive design** — designing for real breakpoints (mobile ~360,
      tablet ~768, desktop ~1024+), not just resizing one layout
- [ ] **Prototyping** — low-fi (structure), hi-fi (polish), interactive
      (clickable flow) — know when each level is enough, don't over-build
- [ ] **Micro-interactions** — basic motion/feedback (button press states,
      loading states, transitions) — depth here belongs to a motion
      specialist, but you need to know when a screen needs one

## 4. Tools (practical proficiency, not just familiarity)

- [ ] **Figma** — core: components, auto-layout, variants, design tokens/
      styles, dev mode handoff
- [ ] **FigJam** — collaborative whiteboarding: flows, brainstorms, retros
- [ ] **Framer** — advanced interactive prototyping and dev-ready handoff
- [ ] Nice-to-have: Sketch, Adobe XD, or Webflow — only if a project
      specifically uses them; don't chase every tool

## 5. Dev-Collaboration Skills (where most self-taught designers fall short)

- [ ] **Basic HTML/CSS literacy** — enough to know what's cheap vs.
      expensive to build, so you don't design things a dev can't ship on
      deadline
- [ ] **Design tokens** — naming and structuring colors/spacing/type as
      variables that map directly to code, not just Figma styles
- [ ] **Handoff discipline** — states, edge cases (empty/error/loading),
      and spacing specs documented, not left for the dev to guess

## 6. Soft Skills (the part infographics always skip)

- [ ] **Rationale communication** — explain *why* a decision was made
      (heuristic, user goal, constraint), not just present the result
- [ ] **Critical self-review** — check your own work against a rubric
      before showing it, instead of shipping first-instinct output
- [ ] **Scope discipline** — pick the smallest layout/pattern that solves
      the problem instead of defaulting to the most elaborate one

## 7. Portfolio & Practice

- [ ] Case studies that show the *process* (problem → research → iterations
      → outcome), not just final screens
- [ ] 2–3 real or self-initiated projects taken end-to-end, not fragments
- [ ] Use portfolioakshay.in as a first UX case study (document the *why*
      behind its layout and animation choices)

---

## Reference: Suggested learning order (for full-stack dev background)

1. **Foundations (#1) + Figma core (#4)** — vocabulary and tool first
2. **UX process (#2)** — research/IA/wireframing (skipping straight to
   visual design is the most common self-taught mistake)
3. **UI craft (#3) + dev-collaboration (#5)** — coding background gives
   a head start over most designers here
4. **Soft skills (#6)** build naturally through #1–3 on real projects
5. **Portfolio (#7)** last, documenting what you learned along the way

---

## Quick-Reference Heuristics & Constants

These are the specific numbers and rules the agent should internalize:

| Rule | Value | Source |
|------|-------|--------|
| Body text contrast ratio | ≥ 4.5:1 (AA) | WCAG 2.2 SC 1.4.3 |
| Large text contrast ratio | ≥ 3:1 (AA) | WCAG 2.2 SC 1.4.3 |
| Minimum tap target | 44 × 44 px | WCAG 2.2 SC 2.5.8 |
| Readable line length | 50–75 characters | Typography best practice |
| Spacing grid base | 8px | Material / industry standard |
| Responsive grid columns | 12 | Bootstrap / industry standard |
| Mobile breakpoint | ~360px | Device data |
| Tablet breakpoint | ~768px | Device data |
| Desktop breakpoint | ~1024px+ | Device data |

### Nielsen's 10 Usability Heuristics (shorthand)

1. Visibility of system status
2. Match between system and real world
3. User control and freedom
4. Consistency and standards
5. Error prevention
6. Recognition rather than recall
7. Flexibility and efficiency of use
8. Aesthetic and minimalist design
9. Help users recognize, diagnose, recover from errors
10. Help and documentation

### Gestalt Principles (shorthand)

- **Proximity** — elements near each other are perceived as grouped
- **Similarity** — elements that look alike are perceived as related
- **Continuity** — the eye follows smooth paths over abrupt changes
- **Closure** — the mind completes incomplete shapes
- **Figure/Ground** — the eye separates foreground from background
- **Common fate** — elements moving together are perceived as grouped
