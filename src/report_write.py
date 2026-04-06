"""Write HTML report files plus sidecar JSON for search indexing."""

from __future__ import annotations

import hashlib
import html as html_module
import json
import re
from pathlib import Path

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_ARGS_DISPLAY_RE = re.compile(r'<meta name="ootp-args-display" content="([^"]*)"', re.IGNORECASE)
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


def args_hash(args_key: dict) -> str:
    """Return an 8-char hex hash of the normalized args dict."""
    payload = json.dumps(args_key, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:8]


def report_filename(base: str, args_key: dict) -> str:
    """Return ``{base}.{hash8}.html`` for the given base name and args."""
    return f"{base}.{args_hash(args_key)}.html"


def sidecar_path_for_html(html_path: Path) -> Path:
    return html_path.with_name(html_path.stem + ".search.json")


def write_report_html(html_path: Path, html: str) -> None:
    """Write the report HTML and a sibling ``*.search.json`` for /reports/search."""
    html_path.write_text(html, encoding="utf-8")
    title = _extract_title(html) or ""
    text = html_to_search_text(html)
    stem = html_path.stem
    # Strip the trailing .hash8 suffix added by report_filename() (e.g. "foo.abc12345" → "foo")
    if "." in stem:
        base, maybe_hash = stem.rsplit(".", 1)
        if len(maybe_hash) == 8 and all(c in "0123456789abcdef" for c in maybe_hash):
            stem = base
    stem_words = stem.replace("_", " ").replace("-", " ")
    if stem_words and stem_words.lower() not in text.lower():
        text = f"{text} {stem_words}".strip()
    m = _ARGS_DISPLAY_RE.search(html)
    args_display = html_module.unescape(m.group(1)) if m else ""
    payload = dict(title=title, text=text, args_display=args_display)
    sidecar_path_for_html(html_path).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
