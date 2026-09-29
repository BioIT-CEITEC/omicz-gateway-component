"""
Generates dark.css — the dark theme for the Tailwind-CDN templates.

Templates use fixed light utility classes (bg-white, text-gray-400, border-gray-100 …).
Instead of adding a dark: variant to every element, dark.css remaps those classes
when <html> has class "dark". Selectors start with `html.dark` so they outrank
Tailwind's own rules (Tailwind's CDN style tag is injected after this file).
Hover / checked variants get their own rules for the same reason.

Run after changing the palette:  python3 frontend/static/css/build_dark_css.py
"""
import os

# ── neutral surfaces and text ────────────────────────────────────────────────
SURFACE   = "#131c2e"   # cards, sidebar (was white)
PAGE      = "#0b1220"   # page background (was #F0F4FA)

BG = {
    "white":    SURFACE,
    "gray-50":  "#172136",
    "gray-50/60": "#172136",   # table headers
    "gray-100": "#1e293b",
    "gray-200": "#283548",
    "gray-300": "#3a475c",
    "gray-400": "#556174",
    "[#F0F4FA]": PAGE,
}
TEXT = {
    "gray-900": "#f1f5f9",
    "gray-800": "#e2e8f0",
    "gray-700": "#cbd5e1",
    "gray-600": "#b4bfcd",
    "gray-500": "#94a3b8",
    "gray-400": "#8390a4",
    "gray-300": "#64748b",
    "gray-200": "#475569",
}
BORDER = {
    "gray-50":  "#1b2539",
    "gray-100": "#1f2a3e",
    "gray-200": "#2b384d",
    "gray-300": "#3a475c",
    "gray-400": "#556174",
}

# ── brand navy: fine as a button background, unreadable as text on dark ───────
BRAND_TEXT   = "#93b4ff"
BRAND_BORDER = "#5d7fd0"

# ── status tints: light pastel backgrounds become translucent colour washes ─
TINTS = {  # name: (rgb of the 500 shade, readable text shade for dark)
    "red":     ("239 68 68",  "#fca5a5"),
    "green":   ("34 197 94",  "#86efac"),
    "emerald": ("16 185 129", "#6ee7b7"),
    "teal":    ("20 184 166", "#5eead4"),
    "blue":    ("59 130 246", "#93c5fd"),
    "indigo":  ("99 102 241", "#a5b4fc"),
    "purple":  ("168 85 247", "#d8b4fe"),
    "amber":   ("245 158 11", "#fcd34d"),
    "yellow":  ("234 179 8",  "#fde047"),
    "orange":  ("249 115 22", "#fdba74"),
}


def esc(cls: str) -> str:
    """Escape a Tailwind class name for use in a CSS selector."""
    out = ""
    for ch in cls:
        out += "\\" + ch if ch in "[]#/:.%()," else ch
    return out


rules: list[str] = []


def rule(classes: list[str], decl: str, variants=("", "hover", "group-hover", "has-[:checked]")):
    for c in classes:
        for v in variants:
            if not v:
                sel = f"html.dark .{esc(c)}"
            elif v == "hover":
                sel = f"html.dark .{esc('hover:' + c)}:hover"
            elif v == "group-hover":
                sel = f"html.dark .group:hover .{esc('group-hover:' + c)}"
            else:
                sel = f"html.dark .{esc('has-[:checked]:' + c)}:has(:checked)"
            rules.append(f"{sel}{{{decl}}}")


for name, val in BG.items():
    rule([f"bg-{name}"], f"background-color:{val}")
for name, val in TEXT.items():
    rule([f"text-{name}"], f"color:{val}")
for name, val in BORDER.items():
    rule([f"border-{name}"], f"border-color:{val}")
    rules.append(f"html.dark .{esc('divide-' + name)}>:not([hidden])~:not([hidden]){{border-color:{val}}}")

# brand
rule(["text-[#0C2461]"], f"color:{BRAND_TEXT}")
rule(["border-[#0C2461]"], f"border-color:{BRAND_BORDER}")
rule(["bg-[#0C2461]/5"], "background-color:rgb(147 180 255 / 0.10)")
rule(["border-[#0C2461]/10", "border-[#0C2461]/20"], "border-color:rgb(147 180 255 / 0.25)")
rule(["bg-[#0C2461]"], "background-color:#1d3a8a")          # solid navy → a bit brighter for contrast
rule(["bg-[#091B4D]"], "background-color:#264aa8")
rule(["text-white"], "color:#fff")                          # keep white text white on hover too

# status tints
for name, (rgb, readable) in TINTS.items():
    rule([f"bg-{name}-50"], f"background-color:rgb({rgb} / 0.12)")
    rule([f"bg-{name}-100"], f"background-color:rgb({rgb} / 0.20)")
    rule([f"border-{name}-100", f"border-{name}-200"], f"border-color:rgb({rgb} / 0.35)")
    rule([f"border-{name}-300"], f"border-color:rgb({rgb} / 0.55)")
    rule([f"text-{name}-600", f"text-{name}-700", f"text-{name}-800"], f"color:{readable}")

# gradients (history fades, sidebar divider)
rules += [
    f"html.dark .from-white{{--tw-gradient-from:{SURFACE} var(--tw-gradient-from-position);"
    "--tw-gradient-to:rgb(19 28 46 / 0) var(--tw-gradient-to-position);"
    "--tw-gradient-stops:var(--tw-gradient-from), var(--tw-gradient-to)}",
    "html.dark .via-gray-200{--tw-gradient-to:rgb(43 56 77 / 0) var(--tw-gradient-to-position);"
    "--tw-gradient-stops:var(--tw-gradient-from), #2b384d var(--tw-gradient-via-position), var(--tw-gradient-to)}",
    "html.dark .to-gray-100{--tw-gradient-to:#1e293b var(--tw-gradient-to-position)}",
]

# base elements
rules += [
    "html.dark{color-scheme:dark}",
    f"html.dark body{{background-color:{PAGE}}}",
    "html.dark input:not([type=checkbox]):not([type=radio]),html.dark select,html.dark textarea"
    f"{{background-color:#0f1829;color:#e2e8f0;border-color:#2b384d}}",
    "html.dark input::placeholder,html.dark textarea::placeholder{color:#64748b}",
    "html.dark .brand-logo{background:#f8fafc;border-radius:8px;padding:4px 6px}",
    "html.dark .shadow-sm,html.dark .shadow{--tw-shadow-color:rgb(0 0 0 / 0.4)}",
]

header = "/* generated by build_dark_css.py — edit the palette there, not here */\n"
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dark.css")
with open(out, "w") as f:
    f.write(header + "\n".join(rules) + "\n")
print(f"wrote {out} ({len(rules)} rules)")
