"""The extractors that vote on leading/trailing text parse; they never fetch.

#716 made every mcmetadata extractor run on every article as a voter. The
vendored newspaper3k extractor built `newspaper.Article(url)` with the default
`fetch_images=True`, so `parse()` downloaded every image on the page to choose
a top image -- straight from the pod, not through the proxy. On
thenewstribune.com, 2026-10-14, that was ten images at ~14.5s each: 2.5 minutes
per article, in a step that is meant to be parse-only.

Checked at the socket, so it holds whichever HTTP library an extractor uses.
"""

from __future__ import annotations

import socket

import pytest

from src.crawler import MCMETADATA_AVAILABLE, other_extractor_texts

pytestmark = pytest.mark.skipif(not MCMETADATA_AVAILABLE, reason="needs mcmetadata")

PAGE = """
<html><head><title>Tacoma nonprofit collects medical equipment</title>
<meta property="og:image" content="https://images.example.invalid/top.jpg">
</head><body><article>
<h1>Tacoma nonprofit collects medical equipment</h1>
<img src="https://images.example.invalid/one.jpg" width="1200" height="800">
<p>On a residential block in Southeast Tacoma, a small nonprofit collects
unused and forgotten medical equipment and works to get it into the hands of
those who need it, often when insurance will not cover the cost.</p>
<img src="https://images.example.invalid/two.jpg" width="1200" height="800">
<p>Volunteers sort walkers, shower chairs and hospital beds from a shelter
built of wire shelving and tarps beside the founder's house, and deliver them
across Pierce County at no charge to the people who ask.</p>
<img src="https://images.example.invalid/logo.svg">
</article></body></html>
"""


@pytest.fixture
def connections(monkeypatch):
    attempts: list[object] = []

    def refuse(*args, **_kwargs):
        attempts.append(args)
        raise OSError("network is off in this test")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    return attempts


def test_voting_opens_no_connection(connections):
    texts = other_extractor_texts("https://www.thenewstribune.com/a.html", PAGE, None)
    assert texts, "no voter produced text, so the check proved nothing"
    assert connections == []


def test_newspaper3k_parses_without_downloading_images(connections):
    from mcmetadata.content import Newspaper3kExtractor

    extractor = Newspaper3kExtractor()
    extractor.extract("https://www.thenewstribune.com/a.html", PAGE)
    assert "Southeast Tacoma" in extractor.content["text"]
    assert connections == []
