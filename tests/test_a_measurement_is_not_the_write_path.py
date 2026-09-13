"""Two additions to the furniture module, and the reasons they are separate.

`flatten` -- every marker comparison folds typographic punctuation to its
ASCII spelling first. A marker list is written with straight quotes; a
publisher's copy is curly. `"week's" in text.lower()` is False against
U+2019, silently, and an ASCII-only fixture cannot see it.

`story_text` -- how much of a body reads as reporting, measured with THE
detector rather than the literal marker list. `strip_boilerplate` answers
the weaker question on purpose: it runs on the write path, where what it
removes is removed from the stored corpus. This one is a measurement, so
it can afford to be right.
"""

from __future__ import annotations

from src.utils.boilerplate import (
    PAYWALL,
    classify_furniture,
    flatten,
    is_boilerplate_segment,
    story_text,
    strip_boilerplate,
)

#: Verbatim from hipaperclips.com. Every apostrophe is U+2019 and the
#: ellipsis is U+2026, because that is what the publisher serves.
CURLY = "See Full Story In This Week’s Image…"


class TestFlatten:
    def test_a_curly_apostrophe_becomes_an_ascii_one(self):
        assert flatten("This Week’s Image") == "this week's image"

    def test_every_quote_dash_and_ellipsis_folds(self):
        assert flatten("‘a’ “b” c–d e—f g…") == "'a' \"b\" c-d e-f g..."

    def test_a_non_breaking_space_becomes_a_space(self):
        assert flatten("a b") == "a b"

    def test_it_lowercases_like_lower_did(self):
        assert flatten("MiXeD Case") == "mixed case"

    def test_an_empty_or_missing_body_is_safe(self):
        assert flatten("") == ""
        assert flatten(None) == ""

    def test_ascii_text_is_untouched(self):
        """The fold must not change what already matched, or every
        existing marker becomes a new question."""
        plain = "to continue reading, please subscribe."
        assert flatten(plain) == plain


class TestFlattenWhereItMatters:
    def test_a_marker_written_in_ascii_matches_a_curly_body(self):
        """THE POINT. Without the fold this returns None and the article
        is sent to a paid model to be told what the sentence says."""
        found = classify_furniture(CURLY)
        assert found is not None
        assert found.kind == PAYWALL

    def test_the_ascii_spelling_of_the_same_sentence_agrees(self):
        """Both spellings reach the same verdict, so the fold is a fix and
        not a second code path."""
        ascii_version = "See Full Story In This Week's Image..."
        assert classify_furniture(CURLY).kind == classify_furniture(ascii_version).kind

    def test_a_dated_pointer_alone_is_not_a_wall(self):
        """ "this week's" is ordinary news prose. It only counts beside an
        access-intent phrase, which is what keeps the fold from turning
        every mention of a date into a paywall."""
        assert classify_furniture("The board meets at this week's session.") is None


class TestStoryText:
    def test_real_reporting_survives(self):
        body = (
            "The council met Tuesday to review the budget. Members voted to "
            "fund the water main replacement on Third Street."
        )
        assert story_text(body) == body

    def test_subscribe_furniture_does_not_survive(self):
        body = "Already a subscriber? Log in here. Start your free trial."
        assert story_text(body) == ""

    def test_the_story_is_kept_and_the_wall_removed(self):
        story = "The council approved the audit Tuesday evening."
        assert story_text(f"{story} Already a subscriber? Log in here.") == story

    def test_an_empty_or_missing_body_is_safe(self):
        assert story_text("") == ""
        assert story_text(None) == ""


class TestWhyItIsNotStripBoilerplate:
    #: Each of these is returned as furniture by `classify_furniture` and
    #: kept by `is_boilerplate_segment`, which is the whole difference.
    KEPT_BY_THE_WEAKER_RULE = (
        "Already a subscriber?",
        "Log in here.",
    )

    #: Neither detector recognises these, recorded rather than asserted
    #: away. Both are subscribe furniture from real captures -- "Claim your
    #: online subscription" is Greenfield Vedette's modal -- and neither is
    #: a WALL: no access-intent phrase, nothing said to be withheld, so
    #: `_gated` correctly declines and no shape rule reaches a short
    #: well-formed sentence. They survive a measurement as if they were
    #: reporting, which is a real ceiling on `story_text` and the reason the
    #: threshold keeps 400-odd characters of headroom.
    RECOGNISED_BY_NEITHER = (
        "Claim your online subscription.",
        "Print subscribers may activate.",
    )

    def test_the_known_gap_is_still_the_known_gap(self):
        """Asserted so closing it is a deliberate change with a measurement
        behind it, and so a widening of the concepts that happens to catch
        these shows up here rather than silently."""
        for segment in self.RECOGNISED_BY_NEITHER:
            assert not is_boilerplate_segment(segment), segment
            assert classify_furniture(segment) is None, segment

    def test_the_literal_list_does_not_recognise_these(self):
        for segment in self.KEPT_BY_THE_WEAKER_RULE:
            assert not is_boilerplate_segment(segment), segment

    def test_the_one_detector_does(self):
        for segment in self.KEPT_BY_THE_WEAKER_RULE:
            assert classify_furniture(segment) is not None, segment

    def test_so_the_two_measures_disagree_and_that_is_deliberate(self):
        """Enough of this furniture clears any whole-body threshold, which
        is exactly how a 909-character stub escaped a 900-character
        ceiling. The measurement had to stop using the weaker rule; the
        write path deliberately still does, because what it drops it drops
        from the stored article."""
        body = " ".join(self.KEPT_BY_THE_WEAKER_RULE * 16)
        assert len(strip_boilerplate(body)) > 500, "the write path keeps it"
        assert story_text(body) == "", "the measurement does not"
