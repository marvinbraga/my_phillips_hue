"""Tests for unified Bootstrap navbar partial across HTML pages."""

from __future__ import annotations

import re

import pytest

KEY_HREFS = (
    'href="/"',
    'href="/lights"',
    'href="/groups"',
    'href="/schedules"',
    'href="/positions-config"',
    'href="/mirror"',
    'href="/health"',
    'href="/chat"',
)

ALL_PAGES = (
    "/",
    "/lights",
    "/groups",
    "/schedules",
    "/positions-config",
    "/mirror",
    "/health",
    "/chat",
)

_NAV_BLOCK = re.compile(r"<nav\b.*?</nav>", re.S)


def _assert_theme_toggle_in_navbar(body: str) -> None:
    assert body.count('id="theme-btn"') == 1
    assert body.count('id="theme-icon"') == 1
    assert 'class="theme-toggle"' not in body
    assert 'id="theme-toggle"' not in body
    nav = _NAV_BLOCK.search(body)
    assert nav is not None
    assert 'id="theme-btn"' in nav.group(0)
    assert 'aria-label="Alternar tema"' in nav.group(0)


def _assert_full_navbar(body: str) -> None:
    assert "navbar" in body
    assert 'aria-label="Navegação principal"' in body
    assert 'id="mainNav"' in body
    assert "breadcrumb" not in body
    for href in KEY_HREFS:
        assert href in body, f"missing nav link {href}"


class TestNavbar:
    def test_mirror_page_has_navbar_and_self_link(self, fastapi_test_client):
        response = fastapi_test_client.get("/mirror")
        assert response.status_code == 200
        body = response.text
        assert "navbar" in body
        assert 'href="/mirror"' in body
        _assert_full_navbar(body)

    def test_groups_page_uses_partial_nav(self, fastapi_test_client):
        response = fastapi_test_client.get("/groups")
        assert response.status_code == 200
        body = response.text
        _assert_full_navbar(body)
        assert "nav-link active" in body or 'aria-current="page"' in body
        # Incomplete breadcrumb-only lists must not appear
        assert "breadcrumb-item" not in body

    def test_schedules_page_uses_partial_nav(self, fastapi_test_client):
        response = fastapi_test_client.get("/schedules")
        assert response.status_code == 200
        body = response.text
        _assert_full_navbar(body)
        assert "breadcrumb-item" not in body

    def test_health_and_index_include_key_links(self, fastapi_test_client):
        for path in ("/", "/health", "/lights", "/chat", "/positions-config"):
            response = fastapi_test_client.get(path)
            assert response.status_code == 200, path
            body = response.text
            assert "navbar" in body, path
            assert 'href="/mirror"' in body, path
            assert 'href="/health"' in body, path
            assert 'href="/chat"' in body, path
            assert 'href="/lights"' in body, path

    @pytest.mark.parametrize("path", ALL_PAGES)
    def test_theme_toggle_lives_inside_navbar(self, fastapi_test_client, path):
        response = fastapi_test_client.get(path)
        assert response.status_code == 200, path
        _assert_theme_toggle_in_navbar(response.text)
