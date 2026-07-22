"""The batch extraction path must keep BOTH sides of the clean.

`_process_batch` already ran the content cleaner, but in dry_run mode and only
to sniff for paywall patterns — the cleaned output was discarded and the raw
capture was written to `content` AND `text`. The consequences were measurable in
production: `content` was byte-identical to `text` for 96,169 of 96,170 stored
articles, 12.1% still carried boilerplate, and the smoke suite's "content
reduction" metric could only ever read 0%.

These tests pin the contract the rest of the pipeline already assumes:
content_cleaner reads `a.content` as its input, entity extraction reads `a.text`
as the cleaned result.
"""

import inspect

import src.cli.commands.extraction as extraction


def _batch_source() -> str:
    return inspect.getsource(extraction._process_batch)


class TestBatchPathKeepsBothSides:
    def test_text_is_bound_to_the_cleaned_body(self):
        src = _batch_source()
        assert (
            '"text": cleaned_text' in src
        ), "the batch INSERT must store the cleaned body in `text`"

    def test_content_is_bound_to_the_raw_capture(self):
        src = _batch_source()
        assert (
            '"content": content_text' in src
        ), "the batch INSERT must keep the raw capture in `content`"

    def test_the_two_columns_are_no_longer_the_same_binding(self):
        """The regression this exists to prevent."""
        src = _batch_source()
        assert '"text": content_text' not in src, (
            "storing the raw capture in `text` is what made content == text for "
            "96,169 of 96,170 articles"
        )

    def test_cleaned_text_falls_back_to_raw(self):
        """A cleaner failure must degrade to today's behaviour, not an empty body.

        The fallback now prefers the DECODED capture, so a cleaner failure on a
        ROT47 page stores recovered prose rather than ciphertext. See
        tests/test_rot47_on_extraction_path.py.
        """
        src = _batch_source()
        assert "cleaned_text = stripped_content or decoded_text or content_text" in src

    def test_hash_describes_the_cleaned_side(self):
        """text_hash is recorded as article_entities.article_text_hash."""
        src = _batch_source()
        assert "calculate_content_hash(cleaned_text)" in src
        assert "calculate_content_hash(content_text)" not in src


class TestCleanerOutputIsStillUsedForPaywallDetection:
    """The fix must not disturb the paywall check that shares stripped_content."""

    def test_paywall_check_still_reads_stripped_content(self):
        src = _batch_source()
        assert "len(stripped_content.strip()) < MIN_CONTENT_LENGTH" in src

    def test_dry_run_is_preserved(self):
        """dry_run only gates wire-marking and suppression, not the cleaning.

        Keeping it True avoids re-introducing those side effects on a path that
        handles wire status separately.
        """
        src = _batch_source()
        assert "dry_run=True" in src
