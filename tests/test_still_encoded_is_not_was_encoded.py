"""The detector asked whether the text HAD been encoded, not whether it still is.

`text_cleaning` decodes a PAIRED `kAm ... k^Am` span and rewrites it,
which consumes the markers the hold looked for. So the two outcomes were
never symmetric:

- the decoder never ran      -> `k^Am` survives -> caught
- the decoder half-succeeded -> `k^Am` consumed -> waved through, with
  every fragment that fell outside a paragraph pair still ciphertext

Measured over the enriched corpus on 2026-09-17: 11 articles carried
`k^Am`, 561 carried ciphertext. The old detector found two per cent of
its own subject.

The residue is encoded HTML, so the markers are now the encodings of the
HTML: `&amp;` is `U2>Aj`, which is why `University Hospital` reached the
corpus as `U2>Ajniversity Hospital` and the gazetteer never matched it.
"""

import pytest

from src.pipeline.review_hold import (
    _ROT47_HTML,
    ROT47_MARKERS,
    _looks_rot47,
    field_defects,
)
from src.pipeline.text_cleaning import _rot47


class TestTheResidueIsCaught:
    """Fragments taken from production bodies the old detector passed."""

    @pytest.mark.parametrize(
        "body",
        [
            "George Kennedy died Friday at U2>Ajniversity Hospital in Columbia.",
            "k2D:56 4=2DDlQE?4>D\\:?=:?6\\C6=4@?E6?E",
            "k9bmkDEC@?8m*|rp D2?5 G@==6J32== =628F6k^DEC@?8mk^9bm",
            "nings or advisories.k9bms2?86C@FD kDA2? 4=2DDlQAC:?E0EC:>Qm",
            "iled this session and their status: k9bmk2 9C67lQ9EEADi^^HHH]",
        ],
    )
    def test_ciphertext_still_in_the_body_is_a_defect(self, body):
        assert _looks_rot47(body)
        assert "text_not_decoded" in field_defects(text=body)


class TestCleanProseIsLeftAlone:
    @pytest.mark.parametrize(
        "body",
        [
            "The Missouri Tigers played in Columbia on Friday night.",
            # `&#` encodes to `UR`, which is inside MISSOURI. A two-character
            # marker flagged 5.6% of clean articles; four characters flags none.
            "SOUTHEAST MISSOURI (89) - Almodovar 21, Terry 21, Stack 9",
            "Hickman will host the Columbia Tournament from April 16-18.",
            "",
        ],
    )
    def test_it_is_not_a_defect(self, body):
        assert not _looks_rot47(body)
        assert "text_not_decoded" not in field_defects(text=body)

    def test_none_is_not_a_defect(self):
        assert not _looks_rot47(None)


class TestTheOldMarkersStillWork:
    """A wider net must not have narrowed the original one."""

    @pytest.mark.parametrize("marker", ["k^Am", "kE23=6", "lQA5C2?<Qm"])
    def test_the_marker_is_still_carried(self, marker):
        assert marker in ROT47_MARKERS

    @pytest.mark.parametrize("marker", ["k^Am", "kE23=6", "lQA5C2?<Qm"])
    def test_a_body_carrying_it_is_still_held(self, marker):
        assert _looks_rot47(f"some text {marker} more text")


class TestTheMarkersAreDerivedNotTranscribed:
    def test_every_derived_marker_decodes_to_the_html_it_came_from(self):
        """Computed from the HTML, so a marker cannot be mistyped."""
        for marker in ROT47_MARKERS:
            if marker in ("k^Am", "kE23=6", "lQA5C2?<Qm"):
                continue  # the originals, kept verbatim
            # ROT47 is its own inverse, so decoding a marker must return
            # exactly the markup it was built from.
            assert _rot47(marker) in _ROT47_HTML, (
                f"{marker!r} decodes to {_rot47(marker)!r}, which is not "
                "one of the HTML strings the markers are derived from"
            )

    def test_no_marker_is_short_enough_to_occur_in_prose(self):
        """`&#` encodes to `UR`. Two characters flagged 5.6% of clean
        articles on a 1,200-article sample; four flags none of them."""
        assert all(len(m) >= 4 for m in ROT47_MARKERS)
