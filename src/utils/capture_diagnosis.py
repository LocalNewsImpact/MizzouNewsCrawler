"""Why a page yielded no links: a wall, an unrendered shell, or nothing new.

Discovery recorded all three as NO_ARTICLES_FOUND, so a blocked source looked
exactly like a quiet one in telemetry. They need different responses --
credentials, a browser, or nothing at all -- and you cannot choose without
knowing which happened.

Thresholds and prose measures come from boilerplate.py, the same module the
content cleaner uses, so a retune moves both together instead of letting a
second copy drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.utils.boilerplate import looks_like_paywall

# Frameworks that ship an empty root element and fill it client-side. Presence
# of one of these alongside almost no anchors is the signature of a page whose
# links exist only after JavaScript runs.
_SPA_ROOT_MARKERS: tuple[str, ...] = (
    'id="root"',
    "id='root'",
    'id="__next"',
    "id='__next'",
    'id="__nuxt"',
    "data-reactroot",
    "ng-app",
    'id="app"',
    "id='app'",
)

_ANCHOR_RE = re.compile(r"<a\s[^>]*href", re.IGNORECASE)
_SCRIPT_RE = re.compile(r"<script\b", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")

# A homepage worth crawling carries many links. Below this, with an SPA marker
# present, the page is a shell rather than a thin homepage.
MAX_ANCHORS_FOR_SHELL = 5

# Visible text as a share of raw HTML. A rendered page is mostly markup, but a
# shell is almost entirely script: under this, there is nothing to parse.
MIN_TEXT_RATIO_FOR_SHELL = 0.05


@dataclass
class CaptureDiagnosis:
    """Why a capture produced no links, with the evidence behind the verdict."""

    reason: str  # "paywall" | "render_required" | "no_new_links" | "empty"
    signals: dict[str, Any] = field(default_factory=dict)

    @property
    def is_blocked(self) -> bool:
        """Whether something stopped us seeing the page, as opposed to the
        page genuinely having nothing new."""
        return self.reason in {"paywall", "render_required"}


def visible_text(html: str) -> str:
    """Rough text content of a page. Not a parser -- enough to measure how
    much of the capture is text rather than script."""
    without_scripts = re.sub(
        r"<script\b.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL
    )
    without_styles = re.sub(
        r"<style\b.*?</style>", " ", without_scripts, flags=re.IGNORECASE | re.DOTALL
    )
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", without_styles)).strip()


def diagnose_capture(html: str | None, links_found: int = 0) -> CaptureDiagnosis:
    """Classify a page capture that yielded no (or too few) links.

    Order matters. A wall is checked first because a paywalled page is often
    ALSO a thin one, and "we were refused" is the more actionable finding.
    """
    if not html or not html.strip():
        return CaptureDiagnosis("empty", {"chars": 0})

    text = visible_text(html)
    anchors = len(_ANCHOR_RE.findall(html))
    scripts = len(_SCRIPT_RE.findall(html))
    text_ratio = (len(text) / len(html)) if html else 0.0
    signals: dict[str, Any] = {
        "chars": len(html),
        "text_chars": len(text),
        "text_ratio": round(text_ratio, 4),
        "anchors": anchors,
        "scripts": scripts,
        "links_found": links_found,
    }

    marker = looks_like_paywall(text)
    if marker:
        signals["paywall_marker"] = marker
        return CaptureDiagnosis("paywall", signals)

    has_spa_root = any(m in html.lower() for m in _SPA_ROOT_MARKERS)
    signals["spa_root"] = has_spa_root
    if anchors <= MAX_ANCHORS_FOR_SHELL and (
        has_spa_root or text_ratio < MIN_TEXT_RATIO_FOR_SHELL
    ):
        return CaptureDiagnosis("render_required", signals)

    # The page rendered and carried links; they were simply not new/eligible.
    return CaptureDiagnosis("no_new_links", signals)
