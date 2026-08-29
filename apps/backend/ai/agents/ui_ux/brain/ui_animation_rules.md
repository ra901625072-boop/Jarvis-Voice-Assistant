# Web Animation & Motion Design Standards (UI/UX Agent)

Comprehensive guidelines, physics parameters, easing curves, and performance constraints for UI animations, micro-interactions, and component transitions.

---

## 1. Core Motion Directives & Performance (60fps GPU Standard)
1. **Zero Layout Thrashing (GPU Only)**:
   - **Allowed Properties**: ONLY animate `transform` (`translate`, `scale`, `rotate`, `skew`) and `opacity`.
   - **Strictly Prohibited**: Never animate `height`, `width`, `top`, `left`, `margin`, or `padding` directly. These trigger CPU layout reflows and cause frame drops.
   - **Layer Promotion**: Use `will-change: transform, opacity;` sparingly on complex moving elements to promote them to GPU composite layers.

2. **Concentric Border Radius Rule**:
   - When nesting rounded elements (e.g. badge inside a card, button inside a modal), inner radius MUST follow:
     $$R_{\text{inner}} = R_{\text{outer}} - \text{Padding}$$
   - Example: Card with `border-radius: 16px` and `padding: 12px` $\rightarrow$ Inner button must have `border-radius: 4px` (or `max(2px, 16px - 12px)`).

---

## 2. Duration Hierarchy & Timing Brackets

| Animation Scope | Ideal Duration | Easing / Curve | Typical Use Case |
| :--- | :--- | :--- | :--- |
| **Micro-Interactions** | `100ms – 150ms` | `ease-out` or Spring | Button click press, badge pop, toggle switch |
| **Standard UI Feedback** | `150ms – 250ms` | `cubic-bezier(0.2, 0, 0, 1)` | Dropdown reveal, tooltip fade, tab underline shift |
| **Structural Transitions** | `250ms – 350ms` | `cubic-bezier(0.16, 1, 0.3, 1)` | Modal dialog entrance, cart drawer slide-over, accordion |
| **Page / View Shifts** | `300ms – 400ms` | `cubic-bezier(0.25, 1, 0.5, 1)` | Route transition, step wizard pane cross-fade |

> [!IMPORTANT]
> Never create animations exceeding **350ms** for standard user workflows to prevent user interface fatigue.

---

## 3. Spring Physics & Easing Tokens

### CSS Motion Variables
```css
:root {
  /* Fast micro-interaction curve */
  --ease-snappy: cubic-bezier(0.2, 0, 0, 1);
  /* Smooth natural deceleration for entering modals & drawers */
  --ease-entrance: cubic-bezier(0.16, 1, 0.3, 1);
  /* Accelerating exit curve for dismissing elements */
  --ease-exit: cubic-bezier(0.4, 0, 1, 1);
  /* Spring-like bounce curve */
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);

  --duration-fast: 150ms;
  --duration-normal: 250ms;
  --duration-slow: 350ms;
}
```

### Framer Motion Spring Presets (React / Next.js)
```typescript
// Snappy feedback for buttons, chips, toggles
export const snappySpring = { type: "spring", stiffness: 400, damping: 30 };

// Gentle, organic motion for modals, bottom sheets, drawers
export const gentleSpring = { type: "spring", stiffness: 260, damping: 24, mass: 0.8 };

// Bouncy accent for success checkmarks and notifications
export const bouncySpring = { type: "spring", stiffness: 350, damping: 18 };
```

---

## 4. Key Animation Patterns & Templates

### A. Modal Dialog Scale & Fade (CSS Keyframes)
```css
.modal-overlay {
  transition: opacity 0.25s var(--ease-entrance);
  backdrop-filter: blur(8px);
}
.modal-dialog {
  animation: modalEnter 0.3s var(--ease-entrance) forwards;
}
@keyframes modalEnter {
  from {
    opacity: 0;
    transform: scale(0.94) translateY(12px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}
```

### B. Slide-Over Cart Drawer (Hardware Accelerated)
```css
.drawer-container {
  position: fixed;
  top: 0;
  right: 0;
  height: 100vh;
  transform: translateX(100%);
  transition: transform 0.35s var(--ease-entrance);
  will-change: transform;
}
.drawer-container.active {
  transform: translateX(0);
}
```

### C. Skeleton Shimmer Loading (GPU Gradients)
```css
.skeleton {
  background: linear-gradient(
    90deg,
    var(--bg-surface) 0%,
    var(--bg-surface-highlight) 50%,
    var(--bg-surface) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.6s infinite ease-in-out;
}
@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
```

---

## 5. Motion Accessibility (WCAG 2.2 Criterion 2.3.3)
Every animation system MUST include an automatic reduced-motion override to respect users with vestibular disorders:

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
In Framer Motion / React:
```tsx
import { useReducedMotion } from "framer-motion";

export const Component = () => {
  const shouldReduceMotion = useReducedMotion();
  const transition = shouldReduceMotion ? { duration: 0 } : snappySpring;
  return <motion.div animate={{ opacity: 1, y: 0 }} transition={transition} />;
};
```
