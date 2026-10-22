"""Controle page: scene deletion markup and the static index.js contract."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = ROOT / "web/static/index.js"
INDEX_TEMPLATE = ROOT / "web/templates/index.html"


def _script_version(template: str) -> str:
    match = re.search(r'/static/index\.js\?v=([\w.-]+)"', template)
    assert match, "index.html must load /static/index.js with a ?v= cache-buster"
    return match.group(1)


def test_controle_page_has_delete_button_modal_and_current_script(
    fastapi_test_client: TestClient,
) -> None:
    response = fastapi_test_client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'id="delete-config-btn"' in html
    assert 'id="deleteConfigModal"' in html
    version = _script_version(INDEX_TEMPLATE.read_text(encoding="utf-8"))
    assert f'/static/index.js?v={version}"' in html
    assert version == "light-intensity-1"


def test_index_js_deletes_with_encoded_name_and_checks_response() -> None:
    js = INDEX_JS.read_text(encoding="utf-8")
    assert "type: 'DELETE'" in js
    assert "'/configurations/' + encodeURIComponent(name)" in js
    assert "data.deleted !== true" in js or "data.deleted === true" in js
    # Local removal only: no reload after a deletion
    assert "loadConfigurations({ reload: true })" not in js
    assert "function remapStateToCache" not in js


def test_index_js_keeps_modal_open_while_delete_in_flight() -> None:
    js = INDEX_JS.read_text(encoding="utf-8")
    assert "'hide.bs.modal'" in js
    assert "Requisição recusada: origem não permitida." in js


def test_index_js_double_click_applies_selected_scene() -> None:
    js = INDEX_JS.read_text(encoding="utf-8")
    assert "$list.on('dblclick', '.config-picker-item'" in js
    assert "applyConfiguration(event);" in js


def test_index_js_scales_colors_by_light_brightness() -> None:
    js = INDEX_JS.read_text(encoding="utf-8")
    assert "function intensityColor(color, brightness)" in js
    assert "intensityColor(view.color, view.brightness)" in js
    assert "intensityColor(p, p.brightness)" in js
