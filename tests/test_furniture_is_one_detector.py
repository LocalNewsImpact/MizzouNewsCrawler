"""Paywalls, cookie modals and nav are ONE detector that reports a kind.

They were three mechanisms in three places -- looks_like_furniture (shape),
looks_like_paywall (literal PAYWALL_MARKERS), and an inline five-string
_cmp_dump_markers list in crawler/__init__.py -- all answering the same
question: is this block scaffolding rather than reporting?

That split is how kq2.com slipped through. Its banner is CLOUDFLARE, not
WPConsent or OneTrust, so none of the five strings matched and 11 of 17
articles in a 4-hour window were stored with 27,372 chars of cookie disclosure
as the article body, every one of them CIN-labelled.

The numbers asserted below were measured against production data on
2026-07-28: the real 27,372-char kq2 capture, and the 200-row CIN export in
exports/cin_last200_20260728.csv. They are written as properties rather than
golden values so they keep meaning when the corpus moves.
"""

from src.utils.boilerplate import (
    CONSENT,
    MIN_EMBEDDED_PROSE_RUN,
    NAV,
    PAYWALL,
    PROMO,
    classify_furniture,
    looks_like_furniture,
    strip_furniture,
)

# Shortened from the real capture. Note what is NOT here: no phrase from the
# old five-string guard, because the vendor is Cloudflare.
COOKIE_TABLE = (
    "Essential cookies enable basic functions and are necessary for the proper "
    "function of the website. Name Description Duration Cookie Preferences This "
    "cookie is used to store the user's cookie consent preferences. 30 days "
    "Cookie Preferences This cookie is used to store the user's cookie consent "
    "preferences. 30 days cf_ob_info The cf_ob_info cookie provides information "
    "on the HTTP Status Code returned by the origin web server. session "
    "__cfruid Used by the content network, Cloudflare, to identify trusted web "
    "traffic. session __cf_bm Cloudflare's bot products identify and mitigate "
    "automated traffic. session _ga This cookie is used to distinguish unique "
    "users by assigning a randomly generated number. 2 years _gid Registers a "
    "unique ID that is used to generate statistical data. 1 day"
)

# Long enough to clear MIN_EMBEDDED_PROSE_RUN, as a real story would be.
STORY = (
    "Ethan Corson announced his campaign for governor on Tuesday morning, "
    "standing outside the county courthouse with about forty supporters. He "
    "said the state budget needs an overhaul and promised to release a detailed "
    "plan in September. Corson has served in the state Senate since 2021, where "
    "he sits on the appropriations committee. His campaign said it had raised "
    "just over two hundred thousand dollars in the first quarter, most of it "
    "from donors inside the district. The primary is scheduled for August."
)

SEDALIA_WALL = (
    "Attention subscribers. To continue reading, you will need to either log "
    "into your subscriber account or purchase a new subscription."
)


class TestOneDetectorReportsAKind:
    def test_a_wall_is_furniture_of_kind_paywall(self):
        found = classify_furniture(SEDALIA_WALL)
        assert found is not None
        assert found.kind == PAYWALL

    def test_a_cookie_table_is_furniture_of_kind_consent(self):
        found = classify_furniture(COOKIE_TABLE)
        assert found is not None
        assert found.kind == CONSENT

    def test_a_story_is_not_furniture_at_all(self):
        assert classify_furniture(STORY) is None

    def test_only_a_wall_is_recoverable(self):
        """The kind exists to pick a status, and this is the bit that does it.

        A wall means a story exists that we did not get -- retryable with
        credentials. A cookie table means there is nothing behind it.
        """
        assert classify_furniture(SEDALIA_WALL).recoverable is True
        assert classify_furniture(COOKIE_TABLE).recoverable is False

    def test_the_old_bool_api_still_answers(self):
        """looks_like_furniture is now a wrapper; call sites must not change."""
        assert looks_like_furniture(COOKIE_TABLE) is True
        assert looks_like_furniture(STORY) is False


class TestVendorIndependence:
    """The actual requirement: catch the vendor nobody has seen yet."""

    def test_cloudflare_table_caught_without_any_cloudflare_phrase(self):
        """Detection must not depend on naming the vendor.

        The five-string guard this replaces contained WPConsent and OneTrust
        strings and matched none of this, which is why kq2 reached the corpus.
        """
        old_guard = (
            "A powerful search engine that organizes",
            "wpconsent-service-google",
            "onetrust-consent-sdk",
            "This cookie is for authentication with your Google account",
            "CookieConsent[stamp]",
        )
        assert not any(m in COOKIE_TABLE for m in old_guard)
        assert classify_furniture(COOKIE_TABLE).kind == CONSENT

    def test_a_wall_worded_in_a_way_no_list_holds(self):
        """Concept matching: an access intent near a gate action.

        This exact sentence is in no marker list in this repo.
        """
        invented = (
            "Want to keep reading this story? Members get unlimited access for "
            "less than a dollar a week."
        )
        found = classify_furniture(invented)
        assert found is not None and found.kind == PAYWALL


class TestPaywallOutranksNoise:
    def test_a_wall_wrapped_in_navigation_is_still_a_wall(self):
        """Calling it navigation would discard the one recoverable finding."""
        found = classify_furniture(
            "Home Sports Obituaries E-Edition. To continue reading, please "
            "subscribe or log in to your account."
        )
        assert found.kind == PAYWALL

    def test_a_newsletter_ask_is_promo_not_a_wall(self):
        """Furniture beside a readable story, so NOT recoverable.

        Filing this as a paywall would queue a credentialed retry for a page
        that was never blocked.
        """
        found = classify_furniture("Subscribe to our newsletter for daily updates.")
        assert found is not None
        assert found.kind == PROMO
        assert found.recoverable is False

    def test_nav_chrome_is_nav(self):
        assert classify_furniture("Skip to main content").kind == NAV


class TestRemovalIsSurgical:
    """The half that matters most: never lose a story to a banner."""

    def test_a_pure_table_leaves_nothing(self):
        result = strip_furniture(COOKIE_TABLE)
        assert result.text == ""
        assert CONSENT in result.kinds

    def test_a_story_below_a_banner_survives_whole(self):
        """The old guard did text_content = None and lost this story.

        This is the entire reason the rewrite exists, so it is asserted on
        content rather than on length.
        """
        result = strip_furniture(COOKIE_TABLE + "\n\n" + STORY)
        assert "Ethan Corson announced his campaign" in result.text
        assert "cf_ob_info" not in result.text
        assert CONSENT in result.kinds

    def test_a_clean_story_is_left_alone(self):
        assert strip_furniture(STORY).text.strip() == STORY.strip()

    def test_scattered_vendor_prose_does_not_survive_as_a_body(self):
        """Why removal works on RUNS rather than on segments.

        Cookie tables contain sentences with no cookie word and no lifetime --
        "The Ray ID of the original failed request." Judged one at a time they
        read as prose, and 3,648 chars of them survived as the article body.
        A run threshold discards them because they never form a long enough
        unbroken stretch; the real table's largest such run measured 387 chars
        against MIN_EMBEDDED_PROSE_RUN.
        """
        assert MIN_EMBEDDED_PROSE_RUN > 387
        result = strip_furniture(
            COOKIE_TABLE
            + " The Ray ID of the original failed request. Applicable values "
            "are 0, 80, and 443."
        )
        assert result.text == ""


class TestShapeIsNotAppliedToSingleSentences:
    """The thresholds are whole-body measures and misfire per-segment."""

    def test_a_real_sentence_about_signing_up_is_not_deleted(self):
        """Measured at 7.1 utility words per 100 -- above the body threshold.

        Deleting this from a story is exactly what removing segments on SHAPE
        would do, which is why only vocabulary and concepts may remove one.
        """
        sentence = (
            "Voters who want to continue receiving mail ballots must sign up "
            "again this year, the clerk said."
        )
        body = STORY + " " + sentence
        assert "mail ballots" in strip_furniture(body).text
