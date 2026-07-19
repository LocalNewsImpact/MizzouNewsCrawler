"""Shared fixtures for dependency contract tests.

These tests exercise the REAL third-party APIs exactly as src/ calls them —
no mocks. They exist so a dependency bump (Dependabot or manual) fails CI
visibly instead of breaking production silently (as transformers 5.x did when
`return_all_scores` was removed while every mocked test stayed green).

They run in two venues:
- regular CI / pre-push: against the current venv (drift canary);
- Image Build Check: inside each freshly built image, against the BUMPED
  versions — the only place a requirements PR's new deps actually exist.

Tests skip cleanly (importorskip / resource probes) when a library or asset
isn't present in the current venue, e.g. torch checkpoints outside the
ml-base/processor images, Chrome outside the crawler image.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# A small but realistic article page: title, byline, date, body paragraphs,
# plus the boilerplate shapes we fight in production (nav header, related
# links, subscribe CTA, copyright footer).
ARTICLE_URL = "https://www.example-gazette.com/2026/03/05/city-council-budget/"

ARTICLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>City Council Approves 2026 Budget After Marathon Session</title>
  <meta name="author" content="Jane Reporter">
  <meta property="article:published_time" content="2026-03-05T09:30:00-06:00">
  <meta property="og:title" content="City Council Approves 2026 Budget After Marathon Session">
</head>
<body>
  <nav><a href="/news">News</a> <a href="/sports">Sports</a> <a href="/obituaries">Obituaries</a></nav>
  <article>
    <h1>City Council Approves 2026 Budget After Marathon Session</h1>
    <p class="byline">By Jane Reporter</p>
    <time datetime="2026-03-05">March 5, 2026</time>
    <p>The city council voted 6-1 late Tuesday to approve a $48 million budget
    for fiscal year 2026, capping a marathon session that stretched past
    midnight and drew dozens of residents to the chamber.</p>
    <p>The approved plan increases funding for road maintenance by twelve
    percent while holding property tax rates flat for the third consecutive
    year, a compromise council members described as hard-won.</p>
    <p>Mayor Pat Alderman said the budget reflects months of public input and
    positions the city to expand its water treatment plant without new debt.</p>
  </article>
  <aside class="related">
    <h3>More Stories</h3>
    <ul>
      <li><a href="/a1">School board weighs bond issue</a></li>
      <li><a href="/a2">Bridge repair to close Main Street</a></li>
    </ul>
  </aside>
  <div class="cta">Subscribe to continue reading. Sign up today for $9.99/month!</div>
  <footer>© 2026 Example Gazette. All rights reserved.</footer>
</body>
</html>
"""

# A sentence that must survive extraction (body) and strings that should not
# dominate it (boilerplate).
BODY_SENTENCE = "voted 6-1 late Tuesday"
BOILERPLATE_MARKERS = ("Subscribe to continue reading", "All rights reserved")

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Gazette</title>
    <link>https://www.example-gazette.com/</link>
    <item>
      <title>City Council Approves 2026 Budget</title>
      <link>https://www.example-gazette.com/2026/03/05/city-council-budget/</link>
      <pubDate>Thu, 05 Mar 2026 09:30:00 -0600</pubDate>
      <description>The council voted 6-1 to approve the budget.</description>
    </item>
  </channel>
</rss>
"""


@pytest.fixture()
def article_html() -> str:
    return ARTICLE_HTML


@pytest.fixture()
def article_url() -> str:
    return ARTICLE_URL


@pytest.fixture()
def rss_xml() -> str:
    return RSS_XML


def find_production_checkpoint() -> Path | None:
    """Locate the production classifier checkpoint if this venue has it."""
    candidates = [Path("/app/models/productionmodel.pt")]  # inside built images
    here = Path(__file__).resolve()
    # Repo layout: tests/dependency_contracts/conftest.py -> parents[2] is the
    # repo root. In-image the suite is mounted at /contracts, which has fewer
    # parents — guard so the helper can't crash in that venue.
    if len(here.parents) > 2:
        candidates.append(here.parents[2] / "models" / "productionmodel.pt")
    env = os.environ.get("PRODUCTION_MODEL_PATH")
    if env:
        candidates.insert(0, Path(env))
    for path in candidates:
        if path.is_file():
            return path
    return None


def pytest_configure(config):
    """Register repo markers for standalone (in-image) runs of this dir."""
    config.addinivalue_line(
        "markers", "allow_network: test may make real network connections"
    )


def chrome_binary_present() -> bool:
    """True when a Chrome/Chromium binary is available (crawler image)."""
    import shutil

    return any(
        shutil.which(name)
        for name in ("chromium", "chromium-browser", "google-chrome", "chrome")
    )
