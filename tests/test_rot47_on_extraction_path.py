"""ROT47 ciphertext must never reach the stored article body.

Lee Enterprises / TownNews sites serve premium paragraphs ROT47-encoded rather
than withholding them. The capture therefore looks healthy — the free preview is
plain prose and the ciphertext begins several sentences in, past the point where
a reader or a reviewer spot-checking the corpus stops looking.

`decode_rot47_segments` has been in the tree and correct all along, but nothing
on the write path called it. Its only two callers were entity extraction, which
decodes into a local and writes nothing back, and the standalone `clean`
command. Entity extraction decoding on read is precisely what hid this: that
stage's output looked right while the cleaner, the classifier, word counts and
the researcher export all saw scrambled text.

Measured in the researcher gold file before the fix: 151 of 15,653 articles
carried ROT47 in the cleaned `text` column, including 112 of 199 from
missourian.com.
"""

import html
import inspect

import src.cli.commands.extraction as extraction
from src.pipeline.text_cleaning import (
    _rot47,
    decode_rot47_segments,
    repair_entity_artifacts,
)


def _encode_premium(plain: str) -> str:
    """Build a capture shaped like the real thing: free preview, then cipher."""
    return f"kAm{_rot47(plain)}k^Am"


PREVIEW = (
    "St. Clair's Lady Bulldogs gave the top seed everything it could handle. "
    "A chance to tie the game at the final buzzer did not fall for St. Clair."
)
PREMIUM = (
    "Lucas is the definition of consistent, Jesse Knott said. In his wins, he "
    "was absolutely dominant, finishing with two falls and two tech falls. It "
    "was great to watch him end his high school career on the winning side."
)


class TestDecodeCapture:
    def test_plain_text_is_returned_unchanged(self):
        """The overwhelmingly common case must be a no-op, not a rewrite."""
        assert extraction._decode_capture(PREVIEW) == PREVIEW

    def test_empty_and_none_are_safe(self):
        assert extraction._decode_capture("") == ""
        assert extraction._decode_capture(None) == ""

    def test_rot47_paragraphs_are_decoded(self):
        capture = f"{PREVIEW}\n{_encode_premium(PREMIUM)}"
        decoded = extraction._decode_capture(capture)
        assert "Lucas is the definition of consistent" in decoded
        assert "two falls and two tech falls" in decoded

    def test_the_free_preview_survives_decoding(self):
        """Decoding must not disturb the plain-text head of the article."""
        capture = f"{PREVIEW}\n{_encode_premium(PREMIUM)}"
        assert "Lady Bulldogs gave the top seed" in extraction._decode_capture(capture)

    def test_no_ciphertext_markers_remain(self):
        capture = f"{PREVIEW}\n{_encode_premium(PREMIUM)}"
        decoded = extraction._decode_capture(capture)
        assert "kAm" not in decoded and "k^Am" not in decoded

    def test_decoding_is_idempotent(self):
        """Re-cleaning runs over already-stored rows; a second pass must not
        re-scramble text an earlier pass already recovered."""
        capture = f"{PREVIEW}\n{_encode_premium(PREMIUM)}"
        once = extraction._decode_capture(capture)
        assert extraction._decode_capture(once) == once

    def test_ciphertext_is_not_mistaken_for_article_length(self):
        """The bug that let fully-paywalled pages pass the length check.

        MIN_CONTENT_LENGTH is applied to the cleaner's output. While the body
        stayed encoded, ~4,000 characters of ciphertext read as a healthy
        article and the paywall branch never fired.
        """
        capture = _encode_premium(PREMIUM)
        assert len(capture) > 150  # would have sailed past the check
        decoded = extraction._decode_capture(capture)
        assert decoded != capture
        assert "definition of consistent" in decoded


class TestHtmlEntitiesAreUnescapedBeforeDecoding:
    """ROT47 maps k -> < and m -> >, so those letters arrive escaped.

    Decoding `&lt;` character-by-character yields `U=Ej`, and `&gt;` yields
    `U8Ej`. Every k and every m in the recovered prose was corrupted that way,
    which is why 29% of affected articles still scanned as ciphertext after
    decoding.
    """

    def test_escaped_k_round_trips(self):
        assert _rot47("asked") == "2D<65"
        on_page = html.escape("2D<65")  # '2D&lt;65'
        assert decode_rot47_segments(f"kAm{on_page}k^Am").strip() == "asked"

    def test_escaped_m_round_trips(self):
        on_page = html.escape(_rot47("community"))
        assert decode_rot47_segments(f"kAm{on_page}k^Am").strip() == "community"

    def test_the_artifact_no_longer_appears(self):
        on_page = html.escape(_rot47("asked the community"))
        out = decode_rot47_segments(f"kAm{on_page}k^Am")
        assert "U=Ej" not in out and "U8Ej" not in out


class TestRepairOfAlreadyStoredDamage:
    """Rows decoded before the unescape fix carry the damage baked in.

    They hold no ROT47 markers and no escaped entities — just prose with every
    k and m replaced — so decoding cannot reach them. The substitution is
    reversible on its own because neither sequence occurs in English.
    """

    def test_repairs_k(self):
        assert (
            repair_entity_artifacts("the feedbacU=Ej we got") == "the feedback we got"
        )

    def test_repairs_m(self):
        assert repair_entity_artifacts("U8Ejayor pro teU8Ej") == "mayor pro tem"

    def test_repairs_repeated_and_adjacent(self):
        assert repair_entity_artifacts("coU8EjU8Ejunity") == "community"

    def test_clean_prose_is_untouched(self):
        prose = "The council voted 4-1 on Tuesday to approve the measure."
        assert repair_entity_artifacts(prose) == prose

    def test_repair_runs_even_without_markers(self):
        """The whole point: damaged rows have no markers left to key off."""
        damaged = "walU=Ejs in and uses theU8Ej"
        assert decode_rot47_segments(damaged) == "walks in and uses them"

    def test_repair_is_idempotent(self):
        once = repair_entity_artifacts("SoU8Eje feedbacU=Ej")
        assert repair_entity_artifacts(once) == once


class TestWritePathDecodesBeforeCleaning:
    """Pin the wiring at each site that persists an article body."""

    def test_batch_path_cleans_the_decoded_text(self):
        src = inspect.getsource(extraction._process_batch)
        assert "decoded_text = _decode_capture(content_text)" in src
        assert "text=decoded_text" in src

    def test_batch_fallback_never_stores_ciphertext(self):
        """A cleaner failure must degrade to decoded prose, not the raw cipher."""
        src = inspect.getsource(extraction._process_batch)
        assert "cleaned_text = stripped_content or decoded_text or content_text" in src

    def test_batch_still_stores_the_raw_capture_in_content(self):
        """`content` keeps the verbatim capture so the decode stays auditable."""
        src = inspect.getsource(extraction._process_batch)
        assert '"content": content_text' in src
        assert '"text": cleaned_text' in src

    def test_recleaning_path_decodes_what_it_reads_back(self):
        """Re-cleaning reads `content` from the database, so it inherits every
        row written before this fix."""
        src = inspect.getsource(extraction._run_post_extraction_cleaning)
        assert "decoded_content = _decode_capture(original_content)" in src
        assert "text=decoded_content" in src
