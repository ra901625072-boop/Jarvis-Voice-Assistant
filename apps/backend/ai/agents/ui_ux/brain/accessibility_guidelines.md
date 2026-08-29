# Accessibility (a11y) & WCAG 2.2 Compliance Guidelines

Standards and deterministic checklists for building accessible, keyboard-navigable, and screen-reader-friendly interfaces.

---

## 1. Core Semantic DOM Principles
- **No "Div-Soup"**: Structure documents using semantic HTML5 elements:
  - `<header>`, `<nav>`, `<main>`, `<article>`, `<section>`, `<aside>`, `<footer>`.
- **Headings Hierarchy**: Strictly maintain hierarchical order (`<h1>` -> `<h2>` -> `<h3>`). Never skip levels for styling purposes.
- **Language Declaration**: Document root MUST declare language: `<html lang="en">`.
- **Responsive Viewport**: Every document `<head>` MUST declare `<meta name="viewport" content="width=device-width, initial-scale=1.0">`.

---

## 2. Accessible Interactive Elements
- **Icon Buttons**: Every button containing only an icon (e.g. `<button><i class="fa fa-trash"></i></button>`) MUST specify `aria-label="Delete item"`.
- **Form Controls & Inputs**:
  - Every `<input>`, `<select>`, `<textarea>` MUST have an associated `<label for="id">` or `aria-label`.
  - Placeholder text MUST NEVER be used as a replacement for explicit field labels.
  - Error messages must link via `aria-describedby="error-id"` and indicate invalid state with `aria-invalid="true"`.
- **Links vs Buttons**:
  - Use `<a>` with a valid `href` for navigation between pages or anchors.
  - Use `<button>` for triggering actions, modals, submissions, or state changes. Never use `<a href="#">` or `<div onclick="...">` for buttons.

---

## 3. Dialogs, Drawers & Modals Checklist
When designing or generating modal dialogs and slide-over drawers:
1. **ARIA Roles**: Element must declare `role="dialog"` (or `role="alertdialog"` for confirmations), `aria-modal="true"`, and `aria-labelledby="modal-title-id"`.
2. **Focus Management**:
   - Save the active element that opened the dialog (`document.activeElement`).
   - Move focus into the first focusable element inside the modal on open.
   - Trap focus inside the dialog while open (cycling Tab / Shift+Tab).
   - Restore focus back to the triggering element upon close.
3. **Keyboard Dismissal**: Pressing the `Escape` key MUST immediately close the modal.
4. **Body Scroll Lock**: Set `document.body.style.overflow = 'hidden'` while modal is active.

---

## 4. Visual & Media Accessibility
- **Images**: All `<img>` tags must include a descriptive `alt="..."` attribute. If purely decorative, specify `alt=""` and `aria-hidden="true"`.
- **Color Independence**: Never convey status or critical information using color alone (e.g. combine red color with an error icon and descriptive text).
- **Focus Rings**: Never remove `:focus` or `:focus-visible` outlines without supplying an accessible high-contrast replacement ring.
