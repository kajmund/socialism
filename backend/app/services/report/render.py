"""Shared report HTML assets (theme CSS for iframe embedding)."""

from __future__ import annotations

from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
THEME_CSS_MARKER = "/*@@REPORT_THEME_CSS@@*/"
REPORT_FONTS_HREF = (
    "https://fonts.googleapis.com/css2?family=Bai+Jamjuree:wght@400"
    "&family=JetBrains+Mono:wght@400;500"
    "&family=Poppins:wght@400;500;600;700&display=swap"
)


def load_report_theme_css() -> str:
    return (ASSETS_DIR / "report_theme.css").read_text(encoding="utf-8")


def inject_report_theme(html: str) -> str:
    """Inline shared Devbrains report CSS (iframe cannot see SPA styles)."""
    if THEME_CSS_MARKER not in html:
        return html
    return html.replace(THEME_CSS_MARKER, load_report_theme_css())
