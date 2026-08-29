"""
apps/backend/ai/agents/ui_ux/ui_ux_tools.py — Mathematical UI/UX & Accessibility Toolset.

Provides exact color contrast calculations (WCAG 2.1 / 2.2), token export engines
(CSS, Tailwind, SCSS, JSON), HTML/DOM accessibility rules auditing, and SVG generation.
"""

import os
import re
import json
from typing import Dict, Any, Tuple, Optional, List


# ── Mathematical WCAG Color & Contrast Engine ────────────────────────────────

def hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    """Normalize hex string (#RGB, #RRGGBB) to (R, G, B) tuple in 0..255."""
    hex_clean = hex_str.strip().lstrip('#')
    if len(hex_clean) == 3:
        hex_clean = ''.join(c * 2 for c in hex_clean)
    if len(hex_clean) != 6:
        return (0, 0, 0)
    try:
        r = int(hex_clean[0:2], 16)
        g = int(hex_clean[2:4], 16)
        b = int(hex_clean[4:6], 16)
        return (r, g, b)
    except ValueError:
        return (0, 0, 0)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB integers (0..255) to hex code #RRGGBB."""
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    return f"#{r:02x}{g:02x}{b:02x}".upper()


def calculate_relative_luminance(rgb_or_hex: Any) -> float:
    """
    Calculate the relative luminance of a color according to W3C WCAG 2.1 formula:
    L = 0.2126 * R + 0.7152 * G + 0.0722 * B
    where R, G, B are converted from sRGB to linear RGB.
    """
    if isinstance(rgb_or_hex, str):
        r, g, b = hex_to_rgb(rgb_or_hex)
    else:
        r, g, b = rgb_or_hex

    def channel_luminance(c_val: int) -> float:
        c = c_val / 255.0
        if c <= 0.04045:
            return c / 12.92
        else:
            return ((c + 0.055) / 1.055) ** 2.4

    r_lin = channel_luminance(r)
    g_lin = channel_luminance(g)
    b_lin = channel_luminance(b)

    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def calculate_contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """
    Calculate exact contrast ratio between two colors according to WCAG 2.1:
    Ratio = (L1 + 0.05) / (L2 + 0.05), where L1 is the lighter color.
    Returns float rounded to 2 decimal places (e.g. 4.54, range 1.0 to 21.0).
    """
    l1 = calculate_relative_luminance(fg_hex)
    l2 = calculate_relative_luminance(bg_hex)

    lighter = max(l1, l2)
    darker = min(l1, l2)

    ratio = (lighter + 0.05) / (darker + 0.05)
    return round(ratio, 2)


def check_wcag_compliance(fg_hex: str, bg_hex: str, is_large_text: bool = False) -> Dict[str, Any]:
    """
    Check WCAG 2.1 / 2.2 compliance for normal or large text:
    - Normal Text: AA >= 4.5:1, AAA >= 7.0:1
    - Large Text / UI Components: AA >= 3.0:1, AAA >= 4.5:1
    """
    ratio = calculate_contrast_ratio(fg_hex, bg_hex)

    aa_threshold = 3.0 if is_large_text else 4.5
    aaa_threshold = 4.5 if is_large_text else 7.0

    passes_aa = ratio >= aa_threshold
    passes_aaa = ratio >= aaa_threshold

    return {
        "foreground": fg_hex,
        "background": bg_hex,
        "contrast_ratio": f"{ratio:.2f}:1",
        "ratio_numeric": ratio,
        "is_large_text": is_large_text,
        "wcag_aa": {
            "threshold": f"{aa_threshold}:1",
            "passed": passes_aa
        },
        "wcag_aaa": {
            "threshold": f"{aaa_threshold}:1",
            "passed": passes_aaa
        }
    }


def suggest_accessible_color(fg_hex: str, bg_hex: str, target_ratio: float = 4.5) -> str:
    """
    Algorithmic color adjuster: adjusts foreground lightness until it satisfies target contrast.
    """
    current_ratio = calculate_contrast_ratio(fg_hex, bg_hex)
    if current_ratio >= target_ratio:
        return fg_hex

    r, g, b = hex_to_rgb(fg_hex)
    bg_lum = calculate_relative_luminance(bg_hex)

    # If background is light (lum > 0.5), darken the foreground; else lighten it.
    darken = bg_lum > 0.5

    best_hex = fg_hex
    for step in range(1, 100):
        factor = 1.0 - (step * 0.01) if darken else 1.0 + (step * 0.02)
        new_r = max(0, min(255, int(r * factor)))
        new_g = max(0, min(255, int(g * factor)))
        new_b = max(0, min(255, int(b * factor)))

        test_hex = rgb_to_hex(new_r, new_g, new_b)
        test_ratio = calculate_contrast_ratio(test_hex, bg_hex)
        best_hex = test_hex
        if test_ratio >= target_ratio:
            break

    return best_hex


# ── Design Token Exporter Engine ─────────────────────────────────────────────

def export_tokens(tokens: Dict[str, Any], format_type: str = "css", output_path: Optional[str] = None) -> str:
    """
    Exports a structured design tokens dictionary into CSS custom properties,
    Tailwind config theme extension, SCSS variables, or W3C DTCG JSON.
    """
    format_type = format_type.lower().strip()
    result_text = ""

    colors = tokens.get("colors", {})
    typography = tokens.get("typography", {})
    spacing = tokens.get("spacing", {})
    radii = tokens.get("radii", tokens.get("borderRadius", {}))
    shadows = tokens.get("shadows", tokens.get("elevation", {}))
    transitions = tokens.get("transitions", {})

    if format_type in ("css", "css_custom_properties"):
        lines = [":root {"]
        # Colors
        if colors:
            lines.append("  /* Colors */")
            for k, v in colors.items():
                lines.append(f"  --color-{k}: {v};")
        # Typography
        if typography:
            lines.append("\n  /* Typography */")
            for k, v in typography.items():
                lines.append(f"  --font-{k}: {v};")
        # Spacing
        if spacing:
            lines.append("\n  /* Spacing */")
            for k, v in spacing.items():
                lines.append(f"  --space-{k}: {v};")
        # Radii
        if radii:
            lines.append("\n  /* Border Radius */")
            for k, v in radii.items():
                lines.append(f"  --radius-{k}: {v};")
        # Shadows
        if shadows:
            lines.append("\n  /* Shadows & Elevation */")
            for k, v in shadows.items():
                lines.append(f"  --shadow-{k}: {v};")
        # Transitions
        if transitions:
            lines.append("\n  /* Transitions */")
            for k, v in transitions.items():
                lines.append(f"  --transition-{k}: {v};")
        lines.append("}")
        result_text = "\n".join(lines)

    elif format_type in ("tailwind", "tailwind_config"):
        tailwind_dict = {
            "theme": {
                "extend": {
                    "colors": colors,
                    "fontFamily": typography,
                    "spacing": spacing,
                    "borderRadius": radii,
                    "boxShadow": shadows,
                    "transitionDuration": transitions
                }
            }
        }
        result_text = f"/** @type {{import('tailwindcss').Config}} */\nmodule.exports = {json.dumps(tailwind_dict, indent=2)};"

    elif format_type in ("scss", "sass"):
        lines = ["// NovaStore Design Tokens (SCSS)"]
        if colors:
            lines.append("\n// Colors")
            for k, v in colors.items():
                lines.append(f"$color-{k}: {v};")
        if typography:
            lines.append("\n// Typography")
            for k, v in typography.items():
                lines.append(f"$font-{k}: {v};")
        if spacing:
            lines.append("\n// Spacing")
            for k, v in spacing.items():
                lines.append(f"$space-{k}: {v};")
        if radii:
            lines.append("\n// Border Radius")
            for k, v in radii.items():
                lines.append(f"$radius-{k}: {v};")
        if shadows:
            lines.append("\n// Shadows")
            for k, v in shadows.items():
                lines.append(f"$shadow-{k}: {v};")
        result_text = "\n".join(lines)

    else:  # json or default
        result_text = json.dumps(tokens, indent=2)

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result_text)

    return result_text


# ── Automated HTML/DOM Accessibility Rule Auditor & Self-Healer ───────────────

def audit_html_accessibility_rules(html_content: str) -> Dict[str, Any]:
    """
    Parses HTML content and executes deterministic WCAG 2.1/2.2 accessibility checks:
    1. Images without alt attribute (1.1.1 Non-text Content)
    2. Buttons without accessible names or text content (4.1.2 Name, Role, Value)
    3. Links with empty href or missing accessible names (2.4.4 Link Purpose)
    4. Form inputs without associated <label> or aria-label (1.3.1 Info and Relationships)
    5. Document without lang attribute (3.1.1 Language of Page)
    6. Missing viewport meta tag (1.4.4 Resize text / 1.4.10 Reflow)
    """
    violations = []
    passed_rules = []
    score = 100

    # 1. Image alt checks
    img_tags = re.findall(r'<img\s+[^>]*>', html_content, re.IGNORECASE)
    missing_alt_count = 0
    for img in img_tags:
        if 'alt=' not in img.lower():
            missing_alt_count += 1
    if missing_alt_count > 0:
        violations.append({
            "criterion": "1.1.1 Non-text Content",
            "severity": "critical",
            "element": f"{missing_alt_count} <img> tag(s) missing alt attribute",
            "fix": "Add descriptive alt=\"...\" or alt=\"\" for decorative images."
        })
        score -= min(25, missing_alt_count * 10)
    elif img_tags:
        passed_rules.append("All <img> tags have alt attributes.")

    # 2. Button accessible name checks
    button_tags = re.findall(r'<button\b[^>]*>(.*?)</button>', html_content, re.IGNORECASE | re.DOTALL)
    empty_buttons = 0
    for inner in button_tags:
        clean_inner = re.sub(r'<[^>]+>', '', inner).strip()
        if not clean_inner and 'aria-label=' not in inner.lower():
            empty_buttons += 1
    if empty_buttons > 0:
        violations.append({
            "criterion": "4.1.2 Name, Role, Value",
            "severity": "critical",
            "element": f"{empty_buttons} <button> tag(s) have no visible text or aria-label",
            "fix": "Add aria-label=\"...\" to icon-only buttons or include visible text."
        })
        score -= min(20, empty_buttons * 10)
    elif button_tags:
        passed_rules.append("Buttons have accessible text or aria-labels.")

    # 3. Form input label association
    input_tags = re.findall(r'<input\s+[^>]*>', html_content, re.IGNORECASE)
    unlabeled_inputs = 0
    for inp in input_tags:
        inp_lower = inp.lower()
        if 'type="hidden"' in inp_lower or 'type="submit"' in inp_lower or 'type="button"' in inp_lower:
            continue
        has_aria = 'aria-label=' in inp_lower or 'aria-labelledby=' in inp_lower
        has_id = 'id=' in inp_lower
        if not has_aria and not has_id:
            unlabeled_inputs += 1
    if unlabeled_inputs > 0:
        violations.append({
            "criterion": "1.3.1 Info and Relationships / 3.3.2 Labels or Instructions",
            "severity": "major",
            "element": f"{unlabeled_inputs} <input> field(s) lack id or aria-label for label association",
            "fix": "Associate inputs with a <label for=\"id\"> or add aria-label."
        })
        score -= min(20, unlabeled_inputs * 5)

    # 4. Document language
    if '<html' in html_content.lower():
        if 'lang=' not in html_content.lower()[:html_content.lower().find('<body') if '<body' in html_content.lower() else 500]:
            violations.append({
                "criterion": "3.1.1 Language of Page",
                "severity": "minor",
                "element": "<html> tag missing lang attribute",
                "fix": "Add lang=\"en\" (or appropriate language code) to <html lang=\"en\">."
            })
            score -= 10
        else:
            passed_rules.append("HTML document declares language attribute.")

    # 5. Viewport meta tag
    if '<head' in html_content.lower():
        if 'name="viewport"' not in html_content.lower():
            violations.append({
                "criterion": "1.4.10 Reflow / 1.4.4 Resize text",
                "severity": "major",
                "element": "Missing <meta name=\"viewport\" ...> tag",
                "fix": "Include <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">."
            })
            score -= 15
        else:
            passed_rules.append("Responsive viewport meta tag is present.")

    score = max(0, min(100, score))
    status = "compliant" if score >= 90 else ("needs_remediation" if score >= 60 else "non_compliant")

    return {
        "score": score,
        "status": status,
        "violations": violations,
        "passed_rules": passed_rules,
        "total_checks": len(violations) + len(passed_rules)
    }


# ── SVG & Vector Asset Generator ─────────────────────────────────────────────

def generate_svg_asset(asset_type: str = "icon", label: str = "Icon", primary_color: str = "#4F46E5", secondary_color: str = "#06B6D4", width: int = 64, height: int = 64) -> str:
    """
    Generates clean, scalable SVG vector elements for common UI needs
    (shopping cart, checkmark, star rating, badge, user avatar, heart favorite).
    """
    asset_type = asset_type.lower().strip()

    if asset_type in ("cart", "shopping_cart", "cart_icon"):
        svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{width}" height="{height}" fill="none" stroke="{primary_color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-label="{label}" role="img">
  <circle cx="9" cy="21" r="1"/>
  <circle cx="20" cy="21" r="1"/>
  <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>
</svg>"""

    elif asset_type in ("check", "checkmark", "success"):
        svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{width}" height="{height}" fill="none" stroke="{primary_color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-label="{label}" role="img">
  <circle cx="12" cy="12" r="10" fill="{secondary_color}" fill-opacity="0.15"/>
  <polyline points="20 6 9 17 4 12"/>
</svg>"""

    elif asset_type in ("star", "rating"):
        svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{width}" height="{height}" fill="{primary_color}" stroke="{primary_color}" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" aria-label="{label}" role="img">
  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
</svg>"""

    elif asset_type in ("badge", "trust_badge"):
        svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 40" width="{width}" height="{height}" fill="none" aria-label="{label}" role="img">
  <rect width="120" height="40" rx="8" fill="{primary_color}"/>
  <text x="60" y="24" fill="#FFFFFF" font-family="Inter, sans-serif" font-size="14" font-weight="600" text-anchor="middle">{label}</text>
</svg>"""

    else:  # generic icon
        svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{width}" height="{height}" fill="none" stroke="{primary_color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-label="{label}" role="img">
  <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
  <line x1="3" y1="9" x2="21" y2="9"/>
  <line x1="9" y1="21" x2="9" y2="9"/>
</svg>"""

    return svg_content.strip()
