"""Write HTML report files plus sidecar JSON for search indexing."""

from __future__ import annotations

import html as html_module
import json
import re
from pathlib import Path

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_WS_RE = re.compile(r"\s+")


def _extract_title(html: str) -> str | None:
    m = _TITLE_RE.search(html)
    if not m:
        return None
    t = m.group(1).strip()
    t = _WS_RE.sub(" ", t)
    if not t:
        return None
    return html_module.unescape(t)


def html_to_search_text(html: str) -> str:
    html = _STYLE_RE.sub(" ", html)
    html = _SCRIPT_RE.sub(" ", html)
    plain = _TAG_RE.sub(" ", html)
    plain = html_module.unescape(plain)
    return _WS_RE.sub(" ", plain).strip()


def sidecar_path_for_html(html_path: Path) -> Path:
    return html_path.with_name(html_path.stem + ".search.json")


def write_report_html(html_path: Path, html: str) -> None:
    """Write the report HTML and a sibling ``*.search.json`` for /reports/search."""
    html_path.write_text(html, encoding="utf-8")
    title = _extract_title(html) or ""
    text = html_to_search_text(html)
    stem_words = html_path.stem.replace("_", " ").replace("-", " ")
    if stem_words and stem_words.lower() not in text.lower():
        text = f"{text} {stem_words}".strip()
    payload = dict(title=title, text=text)
    sidecar_path_for_html(html_path).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
