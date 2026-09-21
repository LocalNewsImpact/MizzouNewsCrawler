"""Rework is one queue with two dispositions, chosen by what was captured.

Reparsing a paywall stub does nothing: the stored body IS the wall, so a
corrected classifier re-derives the same verdict and reports success. Refetching
a good capture is the opposite waste -- a publisher request for bytes already
held, plus a login on a credentialed host.

Measured on WSU 2026-09-20, the 54 `not_article` and `paywall` rows: 9 reparse, 45
refetch. A single "rework means refetch" would be wasteful 9 times; a single
"rework means reparse" would silently fail 45 times and report success.

The two Yakima election stories are the case that shows the discriminator
earning its place. `filing-week-kicks-off-with-46-candidates` was captured today
with `authenticated_session=true`, so its bytes are good and it reparses.
`school-board-races-starting-to-take-shape` was captured before the login ever
worked, so it refetches -- reparsing would re-bless a possibly incomplete
anonymous capture.
"""

from __future__ import annotations

from src.services.rework_disposition import (
    HOLD,
    LEAVE,
    MIN_CAPTURE_CHARS,
    REFETCH,
    REPARSE,
    decide,
)

STORY = "\n".join(
    [
        "Filing week began with 46 candidates filing for 40 local elected "
        "positions across Yakima County on Monday, and the county auditor said "
        "the totals would not be final until the close of business on Friday.",
        "So far two candidates have filed for the coroner seat left vacant last "
        "month, and the council said it would not comment before the deadline "
        "had passed because the filings were still being processed.",
        "Yakima School District, Position 1",
        "Candidate Name (incumbent)",
    ]
)

WALL = "\n".join(
    [
        "Yakima City Council voted Tuesday to approve the budget after two hours "
        "of testimony from residents who packed the chamber to speak about it.",
        "To continue reading please log in or subscribe",
    ]
)

MENU = "Home News Sports Obituaries Classifieds Jobs Legals Contact Us " * 12


def _decide(**over):
    kwargs = dict(
        raw=STORY,
        host="www.yakimaherald.com",
        requires_login=True,
        has_credentials=True,
        authenticated_session="true",
        min_prose_chars=150,
    )
    kwargs.update(over)
    return decide(**kwargs)


class TestAWallIsRefetchedNotReparsed:
    def test_a_stored_wall_wants_a_fresh_capture(self):
        d = _decide(raw=WALL)
        assert d.action == REFETCH
        assert "wall" in d.reason

    def test_that_is_true_even_though_it_was_a_subscriber_fetch(self):
        """A subscriber fetch that still got a wall means the login lapsed.

        Trusting `authenticated_session` over the body here would keep the stub.
        """
        d = _decide(raw=WALL, authenticated_session="true")
        assert d.action == REFETCH

    def test_a_short_wall_is_still_reported_as_a_wall(self):
        """Both refetch, but only one reason points at the login.

        A wall stub is usually short, so if the length floor were checked first
        every wall would be reported as "no usable capture" and an operator would
        never learn that the login is the thing to look at.
        """
        assert len(WALL) < MIN_CAPTURE_CHARS
        d = _decide(raw=WALL)
        assert d.action == REFETCH
        assert "wall" in d.reason

    def test_an_empty_or_tiny_capture_is_refetched(self):
        for body in (None, "", "x" * (MIN_CAPTURE_CHARS - 1)):
            d = _decide(raw=body)
            assert d.action == REFETCH
            assert "no usable capture" in d.reason


class TestAGoodCaptureIsReparsed:
    def test_a_story_misjudged_as_furniture_is_reparsed(self):
        d = _decide()
        assert d.action == REPARSE
        assert d.touches_the_publisher is False

    def test_a_genuine_non_story_is_left_alone(self):
        """Not every wrong-looking row is a mistake. A menu stays a menu."""
        assert _decide(raw=MENU).action == LEAVE

    def test_an_uncredentialed_host_does_not_need_the_subscriber_marker(self):
        """Most WSU hosts need no login, so the marker is correctly absent."""
        d = _decide(
            host="www.nwpb.org", requires_login=False, authenticated_session=None
        )
        assert d.action == REPARSE


class TestTheSubscriberMarkerDecidesCredentialedHosts:
    def test_a_known_anonymous_capture_is_refetched(self):
        d = _decide(authenticated_session="false")
        assert d.action == REFETCH
        assert "not a subscriber fetch" in d.reason

    def test_a_missing_marker_is_unknown_not_anonymous(self):
        """NULL predates the field. The reason must not claim more than we know.

        Most ptleader rows are here: captured before `authenticated_session`
        existed, so unknown. Unknown on a credentialed host means refetch, but it
        is an assumption rather than a measurement and the reason says so.
        """
        d = _decide(authenticated_session=None)
        assert d.action == REFETCH
        assert "predates" in d.reason

    def test_true_as_a_bool_is_accepted_too(self):
        """It arrives from JSON, so it may be a string or a bool."""
        assert _decide(authenticated_session=True).action == REPARSE


class TestRowsThatMustNotBeQueued:
    def test_a_host_we_must_never_fetch_is_held(self):
        """lynnwoodtoday left publisher control and serves gambling spam."""
        d = _decide(host="lynnwoodtoday.com", raw=WALL)
        assert d.action == HOLD

    def test_that_outranks_every_capture_question(self):
        """Decided before the body is read, because no body changes the answer."""
        for body in (None, WALL, STORY, MENU):
            assert _decide(host="lynnwoodtoday.com", raw=body).action == HOLD

    def test_the_www_form_is_caught_as_well(self):
        assert _decide(host="www.mltnews.com", raw=WALL).action == HOLD

    def test_a_paywall_status_with_an_empty_body_is_still_a_wall(self):
        """The body was emptied on purpose when the row was filed.

        `_process_batch` drops the body of a refused capture so it can never be
        read as an article, which leaves `raw` at length 0. A body-only wall test
        therefore sees nothing and falls through to "no usable capture" -- which is
        true but useless, because it hides that a LOGIN is the thing in question.
        All six chinookobserver rows and the one wenatcheeworld row are this
        shape.
        """
        d = _decide(
            status="paywall", raw="", has_credentials=False, requires_login=False
        )
        assert d.action == HOLD
        assert "no login to get past it" in d.reason

    def test_a_paywall_status_with_credentials_is_refetched(self):
        d = _decide(status="paywall", raw="", has_credentials=True, requires_login=True)
        assert d.action == REFETCH
        assert "wall" in d.reason

    def test_a_wall_on_a_host_with_no_login_is_held_not_refetched(self):
        """The case the first version queued forever.

        chinookobserver and wenatcheeworld carry `requires_login=false`, because
        the login was switched off when their subscriber credential was confirmed
        dead. So they look like ordinary anonymous hosts, and refetching would
        re-collect the same wall on every pass.
        """
        d = _decide(raw=WALL, requires_login=False, has_credentials=False)
        assert d.action == HOLD
        assert "no login to get past it" in d.reason
        assert d.touches_the_publisher is False

    def test_a_wall_on_a_host_that_can_log_in_is_refetched(self):
        """With credentials the wall is worth another attempt."""
        d = _decide(raw=WALL, requires_login=True, has_credentials=True)
        assert d.action == REFETCH

    def test_a_credentialed_host_with_no_credentials_is_held(self):
        """chinookobserver and wenatcheeworld: credentials confirmed dead.

        Queueing them produces a failure by construction, which reads as a bug in
        the crawler rather than as a missing password.
        """
        d = _decide(host="chinookobserver.com", has_credentials=False, raw=WALL)
        assert d.action == HOLD
        assert "credentials" in d.reason

    def test_held_rows_never_touch_a_publisher(self):
        for host, creds in (("lynnwoodtoday.com", True), ("x.com", False)):
            d = _decide(host=host, has_credentials=creds, requires_login=True)
            assert d.touches_the_publisher is False


class TestEveryDispositionCarriesAReason:
    def test_no_action_is_returned_without_one(self):
        cases = [
            _decide(),
            _decide(raw=WALL),
            _decide(raw=None),
            _decide(raw=MENU),
            _decide(authenticated_session=None),
            _decide(host="lynnwoodtoday.com"),
            _decide(has_credentials=False),
        ]
        for d in cases:
            assert d.action in (REPARSE, REFETCH, HOLD, LEAVE)
            assert d.reason and d.reason.strip()
