"""Lint templates for UI drift — off-palette colors, legacy classes, unstyled controls.

Usage: python manage.py lint_ui [--warnings-only]
"""
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

# Tailwind default palette colors that must not appear — the app uses the
# chavi-* palette exclusively (chavi-primary/charcoal/sun/sand/peach scales).
OFF_PALETTE_COLORS = (
    "blue", "green", "red", "yellow", "amber", "purple", "indigo", "pink",
    "rose", "cyan", "teal", "emerald", "lime", "orange", "violet", "fuchsia",
    "sky", "slate",
)

OFF_PALETTE_RE = re.compile(
    r"\b(?:bg|text|border|ring|from|via|to|divide|placeholder|accent|decoration|outline|shadow|caret|fill|stroke)-(?:"
    + "|".join(OFF_PALETTE_COLORS)
    + r")-\d{2,3}\b"
)

# Bootstrap-era classes — 'btn' must not be part of a hyphenated hook (create-btn etc.)
LEGACY_RE = re.compile(
    r'class="[^"]*(?<![\w-])btn(?:-(?:primary|secondary|danger|success|warning|info|sm|lg))?\b[^"]*"|'
    r'class="[^"]*\b(?:form-control|form-group|badge-primary)\b'
)
LEGACY_CLASSES = ()
HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
EMPTY_HREF_RE = re.compile(r'href=""\s*|href=""\s*>|href=""$|href=""(?=[^0-9a-zA-Z])')

# Palette hexes that are allowed in inline styles/scripts
ALLOWED_HEX = {
    "#264653", "#2a9d8f", "#e9c46a", "#f4a261", "#e76f51",
    "#eef4f5", "#d9e5e8", "#b3cbd1", "#8db1ba", "#4d7a8a", "#213d49",
    "#1b333d", "#152931", "#0f1f25",
    "#f0faf8", "#dcf4f0", "#b7e9e1", "#78d2c6", "#4bb3a3", "#228578",
    "#1a6d62", "#13554c", "#0c3d36",
    "#fdf8ec", "#faeed4", "#f5dda8", "#f0cd7d", "#eabf6e", "#d9ac45",
    "#b88d33", "#8f6d28", "#664d1d",
    "#fef5ec", "#fce8d3", "#f9d1a7", "#f6ba7b", "#f0a565", "#e58a3f",
    "#c96f2c", "#a05623", "#77411a",
    "#fdf0ec", "#f9ddd3", "#f2baa6", "#ec987a", "#e77f62", "#d95a3a",
    "#b8482e", "#913a26", "#6b2b1c",
    "#fbf7f0", "#f5eee2", "#f5f8f9", "#ecf9f7", "#fef8e7", "#ecf2f4",
    "#fef5ec", "#f8f9fa",
}


class Command(BaseCommand):
    help = "Lint app templates for UI drift (off-palette colors, legacy classes, hardcoded hex)."

    def add_arguments(self, parser):
        parser.add_argument("--warnings-only", action="store_true",
                            help="Report issues without failing the build (exit 0).")
        parser.add_argument("--dir", default=None, help="Template dir override (default: <base>/templates)")

    def handle(self, *args, **opts):
        root = Path(opts["dir"] or Path(settings.BASE_DIR) / "templates")
        issues, warnings = [], []

        for path in sorted(root.rglob("*.html")):
            rel = path.relative_to(root)
            text = path.read_text(errors="replace")

            for m in OFF_PALETTE_RE.finditer(text):
                issues.append(f"{rel}: off-palette color class '{m.group(0)}'")

            for m in LEGACY_RE.finditer(text):
                warnings.append(f"{rel}: legacy Bootstrap-like class in '{m.group(0)[:80]}'")

            for m in HEX_RE.finditer(text):
                if m.group(0).lower() not in ALLOWED_HEX:
                    issues.append(f"{rel}: hardcoded off-palette hex '{m.group(0)}'")

            if EMPTY_HREF_RE.search(text):
                warnings.append(f"{rel}: empty href=\"\"")

            # Raw <table> that misses the chavi-table scheme (styleguide exempt —
            # it intentionally demos unstyled/variant tables)
            if "styleguide" not in str(rel):
                for m in re.finditer(r"<table\b([^>]*)>", text):
                    if "chavi-table" not in m.group(1):
                        warnings.append(f"{rel}: <table> without chavi-table class")

            # Component drift patterns — these should use the component system
            # (styleguide exempt — it intentionally demos raw variants)
            if "allauth" not in str(rel) and "admin" not in str(rel) and "styleguide" not in str(rel):
                lines = text.splitlines()
                def line_of(idx):
                    return lines[text[:idx].count("\n")]
                def ok(m):
                    return "ui-lint:ok" in line_of(m.start())
                for m in re.finditer(r'<span[^>]*class="[^"]*rounded-full[^"]*"', text):
                    if not ok(m):
                        warnings.append(f"{rel}: raw pill span — use badge component ({m.group(0)[:60]})")
                for m in re.finditer(r"<details\b", text):
                    if not ok(m):
                        warnings.append(f"{rel}: raw <details> — use accordion component")
                        break
                for m in re.finditer(r"fixed inset-0", text):
                    if not ok(m):
                        warnings.append(f"{rel}: raw overlay/modal — use modal or loading_overlay component")
                        break
                for m in re.finditer(r"<h1\b", text):
                    if not ok(m):
                        warnings.append(f"{rel}: raw <h1> — use page_header component")
                if re.search(r"{% include ['\"]components/", text):
                    issues.append(str(rel) + ": legacy include 'components/…' partial — use the component system")
                if "slippers" in text or re.search(r"{%\s*#", text) or re.search(r"{%\s*(?:var|fragment)\b", text):
                    issues.append(f"{rel}: slippers syntax — component system is django-components only")

        for msg in issues:
            self.stderr.write(self.style.ERROR("FAIL  " + msg))
        for msg in warnings:
            self.stderr.write(self.style.WARNING("WARN  " + msg))

        self.stdout.write(f"\n{len(issues)} errors, {len(warnings)} warnings in {root}")
        if issues and not opts["warnings_only"]:
            raise SystemExit(1)
