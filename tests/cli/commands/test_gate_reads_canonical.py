"""Classification reads the canonical capture; only sufficiency reads cleaned text.

The save path degrades its input in stages:

    content["content"]  ->  _decode_capture  ->  content_cleaner  ->  stripped
         canonical              decoded            boilerplate removed

Both later stages are correct for deciding what to STORE, and both destroy the
evidence a classifier needs. The wall branch blanks ``content_text`` outright so
a wall is never saved as a body, and ``strip_boilerplate`` removes paywall
phrases because that is its job. The gate then asked the *cleaned* text whether
the page was a wall -- of text those very phrases had just been taken out of.

``looks_like_paywall`` documents the trap in its own docstring ("matches on the
raw body, NOT the stripped one") and the gate did it anyway. The result, over
one production run: 298 of 316 ``not_article`` rows carried a real headline and
a real publish date. Sedalia's prompt matches a marker that has been in
PAYWALL_MARKERS the whole time -- detection never failed, it was asked of the
wrong text.

Separately, this gate ran unconditionally and could overwrite an affirmative
wire classification, discarding an attribution already established from the
byline or the content detector: rows carrying wire=["The Associated Press"] and
wire=["Washington Post"] were filed not_article.

These tests pin the rule rather than the three symptoms, because the next
cleaning rule added is what breaks this again.
"""

import inspect

import pytest

from src.utils.boilerplate import PAYWALL_MARKERS, looks_like_paywall

SEDALIA_WALL = """Attention subscribers

To continue reading, you will need to either log into your subscriber account
or purchase a new subscription.

If you are a digital subscriber with an active subscription, then you already
have an online account. Please log in below to access this article.

Otherwise, click here to view your options for subscribing."""


class TestDetectionWasNeverTheProblem:
    """The marker list already covers these walls."""

    def test_sedalia_wall_is_recognised_on_raw_text(self):
        assert looks_like_paywall(SEDALIA_WALL) is not None

    def test_the_matching_marker_already_shipped(self):
        marker = looks_like_paywall(SEDALIA_WALL)
        assert marker in PAYWALL_MARKERS, (
            "no new phrase was needed -- the gate simply never asked this "
            "function about the canonical capture"
        )

    def test_removing_one_phrase_no_longer_hides_the_wall(self):
        """This assertion was inverted on 2026-07-28, on purpose.

        It used to assert that deleting the matched phrase made the same page
        undetectable -- the real mechanism behind the 298 mislabelled rows, and
        worth pinning while detection was a list of whole phrases.

        Detection is now concept-based (an access intent near a gate action), so
        deleting ONE phrase leaves the wall perfectly visible: Sedalia still
        says "To continue reading ... log into your subscriber account". Keeping
        the old assertion would pin the fragility we set out to remove.
        """
        marker = looks_like_paywall(SEDALIA_WALL)
        stripped = SEDALIA_WALL.lower().replace(marker, "")
        assert looks_like_paywall(stripped) is not None

    def test_stripping_every_wall_phrase_still_hides_it(self):
        """The original point, which still stands.

        Concepts are more robust than phrases, not immune. Strip the access
        intent AND the gate action -- which is what a thorough cleaner does --
        and nothing is left to detect. Classification must therefore still read
        the canonical capture rather than the cleaned text.

        "log in" (not just "log into") is gutted too: _gated() was fixed
        2026-07-29 to search BOTH directions around an access-intent match,
        not just forward, and the widened search reaches "please log in below
        to access this article" once "log into" alone is removed -- a real
        improvement (see the maryvilleforum.com case in
        project_wire_misattribution_bug.md's sibling paywall-detector notes),
        but it means gutting this phrase more thoroughly is what it now takes
        to demonstrate the concept detector's genuine limit.
        """
        gutted = SEDALIA_WALL.lower()
        for phrase in ("continue reading", "log into", "log in", "subscri", "purchase"):
            gutted = gutted.replace(phrase, "")
        assert looks_like_paywall(gutted) is None


class TestGateReadsCanonical:
    """The rule: classify on canonical, measure sufficiency on cleaned."""

    def _gate_source(self) -> str:
        import src.cli.commands.extraction as mod

        src = inspect.getsource(mod)
        start = src.index("THE CANONICAL CAPTURE")
        end = src.index("elif is_insufficient_content", start)
        return src[start:end]

    def test_canonical_is_captured_before_any_branch_blanks_it(self):
        src = self._gate_source()
        assert "canonical_text = _decode_capture(" in src

    def test_paywall_is_classified_on_canonical(self):
        """Not on stripped_content, and not on the cleaner's pattern names."""
        src = self._gate_source()
        assert "looks_like_paywall(canonical_text)" in src

    def test_sufficiency_still_measures_the_cleaned_text(self):
        """The other half of the rule.

        "Is there a story left after cleaning" is genuinely a question about
        the cleaned output -- moving it to the canonical would count furniture
        as article body.
        """
        src = self._gate_source()
        assert "is_insufficient_content = (" in src
        assert "len(stripped_content.strip()) < MIN_CONTENT_LENGTH" in src

    def test_canonical_is_never_reassigned(self):
        """Blanking it to signal a decision is what broke this originally.

        The storage variables (content_text, content["content"]) already carry
        that signal; the canonical must stay readable for classification.
        """
        import src.cli.commands.extraction as mod

        body = inspect.getsource(mod)
        assert body.count("canonical_text = ") == 1

    def test_paywall_detection_is_additive_not_a_replacement(self):
        """A wall any one of the three sources recognises must still count."""
        src = self._gate_source()
        assert "gate_says_paywall" in src
        assert "patterns_matched" in src
        assert "paywall_marker is not None" in src


class TestWireIsTerminal:
    def test_the_shape_gate_cannot_reclassify_wire(self):
        src = TestGateReadsCanonical()._gate_source()
        assert 'if article_status == "wire":' in src, (
            "an affirmative wire classification must short-circuit the shape "
            "gate -- a walled wire story is still a wire story"
        )

    def test_wire_branch_precedes_the_paywall_branch(self):
        """Ordering is the fix; both branches assigning is not enough."""
        src = TestGateReadsCanonical()._gate_source()
        wire = src.index('if article_status == "wire":')
        paywall = src.index("and has_paywall_patterns:")
        assert wire < paywall
