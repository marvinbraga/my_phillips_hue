"""Every page applies the saved theme in <head>, before the stylesheets."""

from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[1] / "web/templates"
PAGES = ["chat", "groups", "health", "index", "lights", "mirror", "positions", "schedules"]


@pytest.mark.parametrize("page", PAGES)
def test_theme_init_runs_before_stylesheets(page: str) -> None:
    html = (TEMPLATES / f"{page}.html").read_text(encoding="utf-8")
    include = html.index('{% include "partials/theme_init.html" %}')
    assert include < html.index("</head>")
    assert include < html.index('rel="stylesheet"')


def test_theme_init_reads_saved_theme() -> None:
    partial = (TEMPLATES / "partials/theme_init.html").read_text(encoding="utf-8")
    assert "localStorage.getItem('theme')" in partial
    assert "setAttribute('data-bs-theme', theme)" in partial
