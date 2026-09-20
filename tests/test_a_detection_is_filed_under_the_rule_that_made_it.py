"""A wire finding is recorded under the rule that found it.

`articles.metadata.wire_detection` is keyed by detector, and the last branch
choosing that key was an unconditional `else`:

    if "gannett_jsonld" in detected_by_list:
        detection_key = "gannett_jsonld"
    elif "structured_metadata" in detected_by_list:
        detection_key = "structured_metadata"
    else:
        detection_key = "hearst_source_name"

`hearst_source_name` is a real rule — it reads Hearst CMS's `window.HRST`
object for a source name — and it was standing in for everything that was
neither Gannett nor `structured_metadata`. So a canonical-URL finding was
written down as a Hearst CMS finding.

Measured in production 2026-09-20: about 25,000 articles carry
`wire_detection.hearst_source_name`, and **not one** of them has
`hearst_source_name` in its own `detected_by`. What actually fired was
`canonical_cross_domain` (14,316), `jsonld_author` (3,438), `meta_author`
(2,563), `og_distributor_category` (1,473) and combinations of those.

The cost was investigative: six WSU articles wrongly marked wire were read off
as "the hearst rule did this", which sent the diagnosis at the wrong code for
two rounds. `detected_by` held the truth the whole time.

Changing the inner key is safe for datadesk, which matches on the presence of
`wire_detection` as text (`WIRE_EVIDENCE_KEYS` in `review/queue.py`) and reads
`detected_by` from inside rather than keying off the name.
"""

from __future__ import annotations

import inspect
import re

from src.cli.commands import extraction


def _key_selection() -> str:
    """The branch that chooses the key, comments stripped.

    The explanation above quotes the old code; an assertion matching comments
    would pass with the fix reverted.
    """
    source = inspect.getsource(extraction._process_batch)
    body = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    start = body.index("detected_by_list = wire_hints.get")
    end = body.index("detection_details[detection_key]")
    return body[start:end]


class TestTheKeyNamesTheRule:
    def test_no_branch_hands_out_hearst_as_a_default(self):
        code = _key_selection()
        assert 'detection_key = "hearst_source_name"' not in code

    def test_the_key_comes_from_detected_by(self):
        code = _key_selection()
        assert re.search(r"detection_key = str\(detected_by_list\[0\]\)", code)

    def test_an_empty_detected_by_is_named_as_such(self):
        """Better an honest "unattributed" than another rule's name."""
        code = _key_selection()
        assert 'detection_key = "unattributed"' in code

    def test_the_two_explicit_rules_still_win(self):
        # These are checked by membership rather than position, because a
        # combination like ['meta_author', 'gannett_jsonld'] should still be
        # filed as Gannett.
        code = _key_selection()
        assert '"gannett_jsonld" in detected_by_list' in code
        assert '"structured_metadata" in detected_by_list' in code

    def test_the_order_is_explicit_rules_then_the_primary_detector(self):
        code = _key_selection()
        gannett = code.index('"gannett_jsonld" in detected_by_list')
        structured = code.index('"structured_metadata" in detected_by_list')
        primary = code.index("detected_by_list[0]")
        fallback = code.index('"unattributed"')
        assert gannett < structured < primary < fallback


class TestTheRuleItStoppedImpersonating:
    def test_hearst_source_name_is_still_a_real_detector(self):
        """The fix must not delete the rule, only stop borrowing its name."""
        from pathlib import Path

        crawler = Path("src/crawler/__init__.py").read_text()
        # It reports itself in `detected_by`, which is what the key now reads.
        assert '"detected_by": ["hearst_source_name"]' in crawler

    def test_it_reads_the_hearst_cms_object(self):
        from pathlib import Path

        crawler = Path("src/crawler/__init__.py").read_text()
        # `window.HRST` is the Hearst CMS global this rule exists to read; a
        # canonical URL has nothing to do with it.
        assert "window.HRST" in crawler
