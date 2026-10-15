"""A curated URL is the reporter's story; a detector does not exclude it.

46 WSU stories sat outside the export on 2026-10-15 -- 33 wire, 8 opinion, 5
obituary -- every one a WSU reporter's own work, on links the curator had
handed over and the wire CHECK already bypassed.
"""

from __future__ import annotations

import pytest

from src.cli.commands import extraction
from src.crawler import _canonical_names_no_publisher


@pytest.mark.parametrize("status", ["wire", "opinion", "obituary", "weather"])
def test_a_curated_row_stays_extracted_and_says_what_was_detected(status):
    meta: dict = {"content_type_detection": {"status": status}}
    got = extraction._curated_keeps_its_status(
        status, '["columbian.com"]', meta, curated=True
    )
    assert got == ("extracted", None)
    assert meta["curated_kept_status"]["detected"] == status
    assert meta["content_type_detection"] == {"status": status}


def test_a_discovered_row_keeps_the_detectors_call():
    meta: dict = {}
    assert extraction._curated_keeps_its_status(
        "wire", '["AP"]', meta, curated=False
    ) == ("wire", '["AP"]')
    assert meta == {}


@pytest.mark.parametrize("status", ["paywall", "not_article", "extracted"])
def test_only_the_detectors_kinds_are_overridden(status):
    assert extraction._curated_keeps_its_status(status, None, {}, curated=True) == (
        status,
        None,
    )


@pytest.mark.parametrize(
    "domain, path, want",
    [
        ("d3lkg5ifzdcnms.cloudfront.net", "/x/34ec/Farmersstruggleamidwar.mp4", True),
        ("example.com", "/media/clip.mp4", True),
        ("cdn.jwplayer.com", "/v2/media/abc", True),
        ("columbian.com", "/news/2025/jan/09/lawmakers-water-resource", False),
    ],
)
def test_a_media_file_or_cdn_canonical_names_no_publisher(domain, path, want):
    assert _canonical_names_no_publisher(domain, path) is want
