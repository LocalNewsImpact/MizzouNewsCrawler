"""A truncated body carrying a subscribe prompt is decided for free.

The LLM content gate spends a call on every article to reach a verdict
that, for the commonest case it sees, a phrase and a length already
settle. The rule takes only that case. It reaches the same status the
paid gate would, under its OWN skip reason, so a reviewer can tell a rule
from a model and this project can measure what the rule costs in recall.

WHAT THE LENGTH MEASURES, AND WHY IT CHANGED
--------------------------------------------
The length that decides is the length of the STORY. The wall's own words
are furniture and are not part of it.

Measuring the whole body counted the furniture as reporting, so the
verdict moved with how much of the wall the extractor happened to
capture. mycouriertribune.com's athlete-of-the-week stub exists twice in
production from the same page: at 343 characters it was caught free, and
at 909 -- the same story, nine characters past a 900-character ceiling,
the difference being captured subscribe furniture -- it had to be paid
for. The cliff was an artefact of the measurement.

Strip the furniture first and the question is the right one: how much
reporting is actually here. A thousand characters of story followed by a
subscribe prompt is a story, and is kept.

Threshold set from evidence, measured 2026-09-13 over 1,406 production
articles: 500 known stubs against 600 cleanly-enriched articles as the
control. Recall 63.6% -> 81.6% against the old whole-body rule, at zero
false positives on the control, whose shortest wall-carrying article
retains 936 characters of story.

The measurement is `story_text`, not `strip_boilerplate`. The latter
consults only the literal marker list and kept "Already a subscriber?",
"Log in here." and "Claim your online subscription." as if they were
reporting -- enough furniture to clear any threshold, which is what the
regression test below catches.
"""

from __future__ import annotations

from src.enrichment.gate import PAYWALL_STUB_MAX_STORY_CHARS, paywalled_stub
from src.enrichment.orchestrator import PAYWALL_RULE_SKIP_REASON
from src.enrichment.types import ArticleInput
from src.utils.boilerplate import story_text

from .test_orchestrator import FULL, run

WALL = "To continue reading, please subscribe."

#: Real sentences, because the threshold is measured after stripping and
#: a run of "xxxx" is not prose -- a filler fixture would be measuring
#: something the production path never sees.
PROSE = (
    "The council met Tuesday to review the budget. "
    "Members voted to fund the water main replacement on Third Street. "
    "The measure passed four to one after an hour of public comment. "
    "Residents of the north side asked about the schedule for repairs. "
    "The city engineer said work would begin in the spring. "
)


def story_of(length: int) -> str:
    """Prose that survives stripping at roughly the length asked for."""
    body = (PROSE * (length // len(PROSE) + 2))[:length]
    assert len(story_text(body)) >= length * 0.8, "fixture is not prose"
    return body


def article(body):
    return ArticleInput("a1", "A headline", body, "ds", "Columbia")


class TestTheRule:
    def test_a_short_walled_body_is_a_stub(self):
        """The phrase is returned, not a bool: which wall fired is the
        evidence the threshold gets retuned on."""
        found = paywalled_stub(f"The council met Tuesday. {WALL}")
        assert isinstance(found, str) and found

    def test_a_long_walled_body_is_left_to_the_gate(self):
        """A full story that also carries a subscribe prompt in its
        furniture is the case the phrase alone gets wrong."""
        body = story_of(1500) + WALL
        assert paywalled_stub(body) is None

    def test_a_short_body_with_no_wall_is_not_a_stub(self):
        assert paywalled_stub("The council met Tuesday.") is None

    def test_an_empty_body_is_not_a_stub(self):
        assert paywalled_stub("") is None
        assert paywalled_stub(None) is None

    # -- what the length is measured over ---------------------------------

    def test_the_wall_is_not_counted_as_story(self):
        """THE REGRESSION. One page produced two rows in production, 343
        and 909 characters, differing only in how much subscribe
        furniture came with them. Under a whole-body rule the second was
        nine characters too long to judge and had to be paid for.

        Piling furniture on cannot change the verdict, because furniture
        is not story."""
        story = "The council met Tuesday and approved the audit. "
        lean = f"{story}{WALL}"
        furniture = (
            " Subscribe now! Log in. Sign up for complimentary access. Already "
            "a subscriber? Log in here. Start your free trial. Subscribe to "
            "continue reading. Need an account? Print subscribers may activate. "
            "Close. Claim your online subscription. For subscribers only."
        )
        padded = f"{story}{WALL}{furniture * 4}"
        assert len(padded) > 900 > len(lean), "the padded body clears the old ceiling"
        assert paywalled_stub(lean) is not None
        assert paywalled_stub(padded) is not None, "furniture must not buy a pass"

    def test_a_thousand_characters_of_story_with_a_wall_is_a_story(self):
        """The rule stated plainly: if the reporting is there, the article
        is kept whatever prompt follows it."""
        body = story_of(1000) + " " + WALL
        assert len(story_text(body)) >= 1000 * 0.8
        assert paywalled_stub(body) is None

    def test_the_threshold_is_exclusive(self):
        """At the threshold there is enough reporting to judge on its
        content, so the rule declines and the paid gate decides."""
        at = story_of(PAYWALL_STUB_MAX_STORY_CHARS + 40) + WALL
        assert paywalled_stub(at) is None
        under = story_of(PAYWALL_STUB_MAX_STORY_CHARS // 4) + WALL
        assert paywalled_stub(under) is not None

    def test_the_threshold_clears_the_closest_real_article(self):
        """936 characters of story is the shortest article in the clean
        negative control (600 enriched articles, no capture furniture)
        that carries a wall phrase. Asserted so a future raise of this
        number has to argue with the evidence rather than with taste."""
        assert PAYWALL_STUB_MAX_STORY_CHARS < 936

    # -- walls that are not written as subscribe prompts -------------------

    def test_a_print_upsell_is_a_wall(self):
        """hipaperclips.com truncates a 394-character audit story and
        points at its own print edition. The content is withheld, which
        is what PAYWALL means, and a paid call had to find it because no
        phrase in the list was written this way."""
        body = (
            "Last week, Holden's City Treasurer, Amber Pemberton, released the "
            "City Of Holden's Final Audit For The Fiscal Year 2025. The "
            "independent auditor's report was conducted by Dana F. Cole & "
            "Company, LLP, Certified Public Accounts. The first 30 pages of the "
            "report contained the conventional information regarding the "
            "methodology and standards used in the audit... "
            "See Full Story In This Week's Image..."
        )
        assert paywalled_stub(body) is not None

    def test_a_print_upsell_survives_the_publishers_own_typography(self):
        """The same body as the publisher actually serves it: curly
        apostrophes and a real ellipsis. `"week's" in text.lower()` is
        False against U+2019, so this fixture is the one that matters --
        an ASCII-only fixture passes while production misses every one."""
        body = (
            "Last week, Holden’s City Treasurer released the City Of "
            "Holden’s Final Audit For The Fiscal Year 2025. The "
            "independent auditor’s report was conducted by Dana F. Cole & "
            "Company, LLP, Certified Public Accounts. The first 30 pages "
            "contained the conventional information regarding the methodology "
            "and standards used in the audit… "
            "See Full Story In This Week’s Image…"
        )
        assert paywalled_stub(body) is not None

    def test_a_named_paper_is_still_a_print_pointer(self):
        """The masthead is a name, not a noun. An edition-word list
        ("edition", "issue", "paper") misses every weekly called
        something -- the Image, the Banner, the Vedette."""
        for masthead in ("Image", "Banner", "Vedette", "Enterprise"):
            body = (
                "The board approved the levy at Monday's meeting after a short "
                f"discussion... See Full Story In This Week's {masthead}..."
            )
            assert paywalled_stub(body) is not None, masthead

    def test_an_article_about_next_weeks_meeting_is_not_a_wall(self):
        """ "this week's" is ordinary news prose. It counts as a print
        pointer only beside an access-intent phrase, so a story that
        merely refers to a dated event is untouched."""
        assert paywalled_stub("The board will vote at next week's meeting.") is None
        assert (
            paywalled_stub(
                "Turnout at this week's fair beat last year's, organisers said."
            )
            is None
        )


class TestTheRuleInTheGate:
    def test_a_stub_costs_no_model_call(self):
        result, stub = run(FULL, article=article(f"Council met. {WALL}"))
        assert stub.calls == []
        assert result.total_cost_usd == 0

    def test_a_stub_lands_where_the_paid_gate_would_put_it(self):
        """Same status, so nothing downstream has to learn a new one: the
        stub still exports with its CIN label and byline."""
        result, _ = run(FULL, article=article(f"Council met. {WALL}"))
        assert result.status == "enrichment_skipped"

    def test_the_rule_says_it_was_the_rule(self):
        result, _ = run(FULL, article=article(f"Council met. {WALL}"))
        assert result.skip_reason == PAYWALL_RULE_SKIP_REASON
        assert result.skip_reason != "paywall_stub"

    def test_a_print_upsell_costs_no_model_call_either(self):
        body = (
            "The audit was released Monday and covers the 2025 fiscal year... "
            "See Full Story In This Week's Image..."
        )
        result, stub = run(FULL, article=article(body))
        assert stub.calls == []
        assert result.skip_reason == PAYWALL_RULE_SKIP_REASON

    def test_a_long_walled_article_still_reaches_the_gate(self):
        result, stub = run(FULL, article=article(story_of(1500) + WALL))
        assert "content_gate" in stub.calls
        assert result.skip_reason != PAYWALL_RULE_SKIP_REASON

    def test_an_ordinary_article_still_reaches_the_gate(self):
        """A real story, not a 24-character sentence: since the no-story
        gate, a body with no reporting in it is refused before any model
        call, and this fixture is meant to test the ordinary path."""
        result, stub = run(FULL, article=article(story_of(600)))
        assert "content_gate" in stub.calls

    def test_the_boilerplate_score_still_wins_first(self):
        """A consent wall that also carries a subscribe prompt is not an
        article at all, and must not be filed as a paywalled story."""
        body = "cookies consent privacy policy vendor list opt out " + WALL
        result, _ = run(FULL, article=article(body))
        assert result.status == "not_article"
        # Named, not NULL. An unnamed refusal is indistinguishable from a
        # completed enrichment in `article_enrichment`; 179 production rows
        # read that way until their entity counts were checked.
        from src.enrichment.gate import BOILERPLATE_SKIP_REASON

        assert result.skip_reason == BOILERPLATE_SKIP_REASON
