"""Every CDN asset loaded by a web template must be pinned and SRI-protected."""

from __future__ import annotations

import base64
import binascii
import re
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
TEMPLATE_FILES = sorted(TEMPLATES_DIR.rglob("*.html"))
# Matches a jsDelivr npm package reference (scoped or not) whose name is not
# followed by "@<version>": ".../npm/pkg/file", ".../npm/pkg", ".../npm/@scope/pkg/file".
UNVERSIONED_JSDELIVR_NPM = re.compile(
    r"cdn\.jsdelivr\.net/npm/(?:@[^/@\"'\s]+/)?[^@/\"'\s?#]+(?=[/\"'\s?#]|$)"
)
SHA384_DIGEST_BYTES = 48


class _ExternalAssetCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "script":
            url = attributes.get("src")
        elif tag == "link" and (attributes.get("rel") or "").lower() == "stylesheet":
            url = attributes.get("href")
        else:
            return
        if url and url.startswith(("http://", "https://", "//")):
            self.assets.append({"tag": tag, "url": url, **attributes})


def _external_assets(path: Path) -> list[dict[str, str | None]]:
    collector = _ExternalAssetCollector()
    collector.feed(path.read_text(encoding="utf-8"))
    return collector.assets


def test_templates_are_discovered() -> None:
    assert len(TEMPLATE_FILES) >= 8


def _integrity_tokens(integrity: str) -> list[str]:
    return integrity.split()


@pytest.mark.parametrize("template", TEMPLATE_FILES, ids=lambda p: p.name)
def test_external_assets_have_sri(template: Path) -> None:
    for asset in _external_assets(template):
        integrity = asset.get("integrity") or ""
        assert integrity.startswith("sha384-"), (
            f"{template.name}: {asset['url']} lacks sha384 integrity"
        )
        assert asset.get("crossorigin") == "anonymous", (
            f"{template.name}: {asset['url']} lacks crossorigin=anonymous"
        )


@pytest.mark.parametrize("template", TEMPLATE_FILES, ids=lambda p: p.name)
def test_no_unversioned_jsdelivr_npm_urls(template: Path) -> None:
    text = template.read_text(encoding="utf-8")
    assert not UNVERSIONED_JSDELIVR_NPM.search(text), (
        f"{template.name} references an unpinned jsDelivr npm package"
    )


@pytest.mark.parametrize("template", TEMPLATE_FILES, ids=lambda p: p.name)
def test_integrity_values_are_well_formed_sha384(template: Path) -> None:
    for asset in _external_assets(template):
        tokens = _integrity_tokens(asset.get("integrity") or "")
        assert tokens, f"{template.name}: {asset['url']} has empty integrity"
        for token in tokens:
            algorithm, _, digest = token.partition("-")
            assert algorithm == "sha384", (
                f"{template.name}: {asset['url']} uses {algorithm!r}; only sha384 is accepted"
            )
            try:
                raw = base64.b64decode(digest, validate=True)
            except binascii.Error as exc:
                pytest.fail(
                    f"{template.name}: {asset['url']} integrity is not base64: {exc}"
                )
            assert len(raw) == SHA384_DIGEST_BYTES, (
                f"{template.name}: {asset['url']} integrity decodes to {len(raw)} bytes, "
                f"expected {SHA384_DIGEST_BYTES}"
            )


def test_same_url_has_same_integrity_across_templates() -> None:
    seen: dict[str, set[str]] = defaultdict(set)
    where: dict[str, list[str]] = defaultdict(list)
    for template in TEMPLATE_FILES:
        for asset in _external_assets(template):
            url = asset["url"] or ""
            seen[url].add(asset.get("integrity") or "")
            where[url].append(template.name)
    inconsistent = {
        url: sorted(values) for url, values in seen.items() if len(values) > 1
    }
    assert not inconsistent, (
        "Same CDN URL carries different integrity values: "
        + "; ".join(
            f"{url} in {sorted(set(where[url]))}: {vals}"
            for url, vals in inconsistent.items()
        )
    )


@pytest.mark.parametrize(
    "snippet",
    [
        'src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"',
        'src="https://cdn.jsdelivr.net/npm/marked"',
        "src='https://cdn.jsdelivr.net/npm/marked'",
        'src="https://cdn.jsdelivr.net/npm/@popperjs/core/dist/umd/popper.min.js"',
        'src="https://cdn.jsdelivr.net/npm/@popperjs/core"',
        "https://cdn.jsdelivr.net/npm/marked",
    ],
)
def test_unversioned_regex_flags_unpinned_urls(snippet: str) -> None:
    assert UNVERSIONED_JSDELIVR_NPM.search(snippet)


@pytest.mark.parametrize(
    "snippet",
    [
        'src="https://cdn.jsdelivr.net/npm/marked@15.0.12/marked.min.js"',
        'src="https://cdn.jsdelivr.net/npm/dompurify@3.4.16/dist/purify.min.js"',
        'src="https://cdn.jsdelivr.net/npm/@popperjs/core@2.11.8/dist/umd/popper.min.js"',
        'src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1"',
    ],
)
def test_unversioned_regex_accepts_pinned_urls(snippet: str) -> None:
    assert not UNVERSIONED_JSDELIVR_NPM.search(snippet)
