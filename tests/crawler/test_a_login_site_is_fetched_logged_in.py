"""A publisher with a login is fetched logged in, from the first request.

The anonymous HTTP paths return the wall, and a wall is a 200 with content:
extraction accepts it, stores the stub, and the browser -- the only place
`_ensure_authenticated` runs -- is never reached. On 2026-09-18 that filed 13
of 19 Port Townsend Leader articles as `paywall` against a credential known to
work, off a page whose own text read "access this content ... login".
"""

from __future__ import annotations

import inspect

from src.crawler import ContentExtractor


class TestTheHostIsNormalisedTheWaySourcesStoresIt:
    def test_www_userinfo_and_port_are_stripped(self):
        for given, want in [
            ("www.ptleader.com", "ptleader.com"),
            ("ptleader.com:443", "ptleader.com"),
            ("user@www.ptleader.com:8080", "ptleader.com"),
            ("PTLeader.com", "ptleader.com"),
        ]:
            assert ContentExtractor._bare_host(given) == want

    def test_an_empty_domain_is_not_an_error(self):
        assert ContentExtractor._bare_host("") == ""
        assert ContentExtractor._bare_host(None) == ""


class TestRequiresLogin:
    def _extractor(self, monkeypatch, answer):
        obj = ContentExtractor.__new__(ContentExtractor)
        monkeypatch.setattr(
            ContentExtractor, "_get_domain_auth_config", lambda self, host: answer
        )
        return obj

    def test_a_configured_publisher_requires_login(self, monkeypatch):
        obj = self._extractor(monkeypatch, {"auth_type": "simplecirc"})
        assert obj._requires_login("www.ptleader.com") is True

    def test_a_publisher_without_a_config_does_not(self, monkeypatch):
        """`_get_domain_auth_config` returns None unless sources.requires_login
        is set, so the two callers cannot disagree about who needs a login."""
        obj = self._extractor(monkeypatch, None)
        assert obj._requires_login("www.kitsapsun.com") is False

    def test_a_lookup_failure_does_not_block_extraction(self, monkeypatch):
        """A database hiccup must not turn every host into a browser fetch."""
        obj = ContentExtractor.__new__(ContentExtractor)

        def boom(self, host):
            raise RuntimeError("no database")

        monkeypatch.setattr(ContentExtractor, "_get_domain_auth_config", boom)
        assert obj._requires_login("ptleader.com") is False


# The branching itself is covered behaviourally in test_the_fetch_plan.py.
# It used to be asserted here by matching source strings, which broke on a
# restructure that changed no behaviour -- the reason those went.


class TestOneSessionPerRun:
    def test_the_driver_is_shared_and_reused_not_rebuilt_per_article(self):
        """One browser session for the run: the driver is class-level, so the
        login survives between articles."""
        from src.crawler import ContentExtractor

        assert hasattr(ContentExtractor, "_shared_persistent_driver")
        assert hasattr(ContentExtractor, "_authenticated_domains")

    def test_the_login_cache_clears_only_when_the_driver_closes(self):
        """Clearing it any earlier would re-login per article; clearing it later
        would carry a dead session into a fresh browser."""

        from src.crawler import ContentExtractor

        src = inspect.getsource(ContentExtractor.close_persistent_driver)
        assert "_authenticated_domains = set()" in src

    def test_the_session_is_established_before_navigation(self):
        """A login after navigation does not carry cookies into the article."""

        from src.crawler import ContentExtractor

        src = inspect.getsource(ContentExtractor._extract_with_selenium)
        assert src.index("_ensure_authenticated") < src.index(
            "_navigate_with_human_behavior"
        )


class TestALoggedInPageIsNotAChallenge:
    """`_detect_captcha_or_challenge` returns True for the word "recaptcha"
    anywhere in the page source, and a logged-in article page carries it in
    its comment form. On 2026-09-19 the first credentialed re-fetch of
    ptleader.com spent ten minutes on one URL in the anonymous bypass ladder
    -- modal closing, driver resets, press-and-hold -- against a page whose
    article text had already been parsed, with a domain backoff of up to
    ninety minutes queued behind it for the other sixteen."""

    def _extractor(self, monkeypatch, answer):
        obj = ContentExtractor.__new__(ContentExtractor)
        monkeypatch.setattr(
            ContentExtractor, "_get_domain_auth_config", lambda self, host: answer
        )
        return obj

    def test_the_check_is_off_for_a_login_gated_host(self, monkeypatch):
        assert (
            self._extractor(
                monkeypatch, {"mechanism": "simplecirc"}
            )._challenge_check_applies("www.ptleader.com")
            is False
        )

    def test_and_on_for_everyone_else(self, monkeypatch):
        assert (
            self._extractor(monkeypatch, None)._challenge_check_applies(
                "www.kitsapsun.com"
            )
            is True
        )

    def test_every_detection_in_navigation_is_behind_the_check(self):
        source = inspect.getsource(ContentExtractor._navigate_with_human_behavior)
        detections = source.count("self._detect_captcha_or_challenge(")
        guarded = source.count("self._challenge_check_applies(")
        assert detections == 2, "the two detection sites this guards"
        assert guarded == detections + 1, (
            "each detection guarded, plus the guard that routes a credentialed "
            "host away from the subscription-wall scan"
        )

    def test_the_backoff_ladder_is_behind_the_check_too(self):
        source = inspect.getsource(ContentExtractor.extract_content)
        assert "if not self._challenge_check_applies(domain):" in source
        assert source.index(
            "if not self._challenge_check_applies(domain):"
        ) < source.index("self._handle_captcha_backoff(domain)")


class TestALoggedInPageIsJudgedByItsText:
    """`_detect_subscription_wall` counts marketing phrases anywhere in the page
    and fires at two. A logged-in ptleader page carries "subscribe",
    "subscription", "subscriber" and "enter your email" in its footer, so on
    2026-09-19 every article of a working session logged "Subscription wall
    detected (4 indicators found)" and then extracted the full story -- two
    ~80-second stalls per article for a verdict that was wrong."""

    # Length matters: the ptleader bodies this recovered run 1,791-4,483 chars,
    # where a one-line newsletter tail is a rounding error. A 300-char fixture
    # would put the tail's utility words over MAX_UTILITY_WORD_RATE on their own.
    STORY = (
        "During its Oct. 21 meeting, the Port Townsend City Council authorized the "
        "city manager to award a contract for the Mountain View Commons portable. "
        "Councilmembers said the building has been vacant since the spring and that "
        "the YMCA would take on maintenance under the agreement. The vote was "
        "unanimous, with one member absent. The council heard from several residents "
        "who said the portable had been a fixture of the commons for two decades and "
        "asked what would happen to the programs it housed. City staff said the "
        "agreement transfers maintenance to the YMCA but leaves the building in "
        "public ownership, and that a report on the programs would come back to the "
        "council in the spring. The mayor said the arrangement had been discussed at "
        "three previous meetings and that the city had no money budgeted for the "
        "repairs the building needs. A representative of the YMCA told the council "
        "the organization intended to keep the space open to the same groups that "
        "use it now, and that it would apply for a county grant to pay for a new "
        "roof before the winter."
    )
    # The tail production actually leaves on a ptleader story, in proportion.
    TAIL = " For more stories like this, sign up for our newsletter."
    # A body that is only furniture: what a lapsed session gets back.
    FURNITURE = (
        "Subscribe Subscription Subscriber Enter your email Sign in Register now "
        "Create an account Get unlimited access Members only Premium content"
    )

    def _extractor(self, monkeypatch, body):
        obj = ContentExtractor.__new__(ContentExtractor)
        monkeypatch.setattr(
            ContentExtractor,
            "_get_domain_auth_config",
            lambda self, h: {"mechanism": "simplecirc"},
        )
        monkeypatch.setattr(
            ContentExtractor,
            "_phase",
            lambda self, name: __import__("contextlib").nullcontext(),
        )
        monkeypatch.setattr(
            ContentExtractor, "_extract_content", lambda self, soup: body
        )
        return obj

    class _Driver:
        page_source = "<html><body>whatever</body></html>"

    def test_a_story_carrying_the_newsletter_tail_is_not_a_wall(self, monkeypatch):
        obj = self._extractor(monkeypatch, self.STORY + self.TAIL)
        assert obj._logged_in_page_withheld_the_story(self._Driver(), "u") is False

    def test_no_story_means_the_session_is_not_getting_the_text(self, monkeypatch):
        obj = self._extractor(monkeypatch, self.FURNITURE)
        assert obj._logged_in_page_withheld_the_story(self._Driver(), "u") is True

    def test_a_driver_fault_is_not_a_verdict(self, monkeypatch):
        obj = ContentExtractor.__new__(ContentExtractor)
        monkeypatch.setattr(
            ContentExtractor, "_get_domain_auth_config", lambda self, h: {"m": 1}
        )
        monkeypatch.setattr(
            ContentExtractor,
            "_phase",
            lambda self, name: __import__("contextlib").nullcontext(),
        )

        class _Broken:
            @property
            def page_source(self):
                raise RuntimeError("driver gone")

        assert obj._logged_in_page_withheld_the_story(_Broken(), "u") is False

    def test_navigation_routes_a_credentialed_host_away_from_the_keyword_scan(self):
        """The gate, and what is inside it, rather than the two lines adjacency.

        Asserted on order rather than on the two statements being consecutive: a
        session-lapse check now sits between them, which is right -- a dropped
        login is asked about BEFORE the body is judged, because the body cannot
        distinguish a lapse from a short story. The invariant here is unchanged,
        that a credentialed host reaches the body judgement and never the keyword
        scan.
        """
        source = inspect.getsource(ContentExtractor._navigate_with_human_behavior)
        gate = source.index("if not self._challenge_check_applies(domain):")
        body_judgement = source.index("if self._logged_in_page_withheld_the_story(")
        assert gate < body_judgement
        assert body_judgement < source.index("modal_closed = self._try_close_modals(")
        assert body_judgement < source.index("if self._detect_subscription_wall(")

    def test_the_subscription_modal_dance_is_skipped_for_a_credentialed_host(self):
        """Each `_try_close_modals` attempt cost ~80 seconds on 2026-09-19, and a
        subscriber's modal is not what withholds the text. The gate returns
        before the subscription-wall path is reached; the only earlier call sits
        inside the CAPTCHA branch, which `_challenge_check_applies` already
        closes for this host."""
        source = inspect.getsource(ContentExtractor._navigate_with_human_behavior)
        gate = source.index("if not self._challenge_check_applies(domain):")
        assert gate < source.index("modal_closed = self._try_close_modals(")
        assert gate < source.index("if self._detect_subscription_wall(")
