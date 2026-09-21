"""A session is confirmed at the fetch, not assumed from the login.

`_session_state` answers a weaker question than it looks like it does: is this
host in `ContentExtractor._authenticated_domains` -- did THIS DRIVER complete a
login for it earlier in its life. That is a claim about history. A session can
lapse mid-run, and on 2026-09-20 a yakimaherald fetch logged

    AUTHENTICATED SESSION GOT NO STORY ... The login may have lapsed or been
    refused.

while the driver still believed it was signed in. Inference is how that becomes a
silent extraction failure.

The existing catch reads the BODY (`_logged_in_page_withheld_the_story` ->
`looks_like_article`). It is a good safety net and a bad confirmation: it cannot
tell a lapsed session from a genuinely short story, which is the exact inference
this project ruled out on metered sites -- and #644 showed how badly body-shape
heuristics misjudge real articles, filing an election-filing story as furniture.

So ask the cookies. Every credentialed host now carries a witnessed login, and
five of the seven left session cookies behind:

| host | signature |
| --- | --- |
| yakimaherald, union-bulletin | `igmAuth` |
| tdn | `tncms-auth`, `tncms-authtoken` |
| columbian | `active_subscription_confirmed`, `blaize_jwt` |
| ptleader | `wordpress_logged_in_<hash>` |
| pendoreillerivervalley, spokesman | none -- a 302 |

Those last two are why `unverifiable` exists as a distinct answer. Their proof is
transactional, visible only during the login, so there is no cookie to re-check
and reporting them as lapsed would refuse every fetch on them.
"""

from __future__ import annotations

import pytest

from src.crawler.authenticated_login import session_signature, session_still_held

WITNESSED_YAKIMA = {
    "witnessed": {
        "first_party_cookies_added": [
            "igmAuth@yakimaherald.com",
            "igmContent@yakimaherald.com",
            "nxt_alng_YHR_YHRCONFIG_PROD@yakimaherald.com",
        ]
    }
}

WITNESSED_PTLEADER = {
    "witnessed": {
        "first_party_cookies_added": [
            "wordpress_logged_in_9e191e36defa303b587b3ecedee6df9d@ptleader.com",
            "memberpress_return_url@ptleader.com",
            "PHPSESSID@ptleader.com",
        ]
    }
}

#: eType and Auth0. Proven by a redirect, so the cookie list is empty.
WITNESSED_BY_REDIRECT = {
    "witnessed": {
        "first_party_cookies_added": [],
        "auth_redirects": [
            [302, "https://www.pendoreillerivervalley.com/account/etype-login"]
        ],
    }
}


class _Driver:
    def __init__(self, names, raises=False):
        self._names = names
        self._raises = raises

    def get_cookies(self):
        if self._raises:
            raise RuntimeError("driver is gone")
        return [{"name": n, "value": "x"} for n in self._names]


class TestTheSignatureIsNamesOnly:
    def test_it_reads_the_witnessed_cookies(self):
        assert session_signature(WITNESSED_YAKIMA) == {
            "igmAuth",
            "igmContent",
            "nxt_alng_YHR_YHRCONFIG_PROD",
        }

    def test_the_domain_is_stripped(self):
        """Stored as `name@domain`; the name is what survives a new session."""
        assert all("@" not in n for n in session_signature(WITNESSED_YAKIMA))

    def test_a_hashed_name_is_kept_whole(self):
        """WordPress hashes the site URL into the name.

        It looks like a value and is a stable per-site NAME, so an exact match
        per host is right -- and matching it across hosts would be wrong.
        """
        assert (
            "wordpress_logged_in_9e191e36defa303b587b3ecedee6df9d"
            in session_signature(WITNESSED_PTLEADER)
        )

    def test_a_redirect_proof_has_no_signature(self):
        assert session_signature(WITNESSED_BY_REDIRECT) == frozenset()

    def test_an_unwitnessed_host_has_no_signature(self):
        for config in ({}, None, {"witnessed": {}}, {"login_url": "x"}):
            assert session_signature(config) == frozenset()

    def test_no_value_is_ever_read(self):
        """Values were deliberately never recorded; only lengths were."""
        config = {"witnessed": {"first_party_cookies_added": ["igmAuth@x.com"]}}
        assert session_signature(config) == {"igmAuth"}


class TestTheCheckIsAffirmative:
    def test_a_held_session_is_confirmed(self):
        driver = _Driver(["igmAuth", "_ga", "AWSALB"])
        assert session_still_held(driver, session_signature(WITNESSED_YAKIMA)) is True

    def test_one_surviving_cookie_is_enough(self):
        """A publisher may rotate some of its cookies and keep the auth one.

        Requiring all of them would refuse fetches on a session that is plainly
        still live, which is the failure mode this exists to prevent.
        """
        driver = _Driver(["igmAuth"])
        assert session_still_held(driver, session_signature(WITNESSED_YAKIMA)) is True

    def test_a_dropped_session_is_reported(self):
        driver = _Driver(["_ga", "AWSALB", "panoramaId"])
        assert session_still_held(driver, session_signature(WITNESSED_YAKIMA)) is False

    def test_ad_tech_cookies_cannot_stand_in(self):
        """The stored signature is already session-only.

        `partition_evidence` removed the infrastructure and ad-tech families
        before it was recorded, so a load balancer's affinity cookie cannot pass
        for a login. spokesman reported seven of those as "session cookies" once.
        """
        driver = _Driver(["_cc_id", "connectId", "aws-waf-token", "incap_ses_351"])
        assert session_still_held(driver, session_signature(WITNESSED_YAKIMA)) is False


class TestNoneIsNotFalse:
    def test_an_empty_signature_is_unanswerable_not_lapsed(self):
        """etype and auth0. Reporting them lapsed would refuse every fetch."""
        driver = _Driver(["tipssid"])
        assert (
            session_still_held(driver, session_signature(WITNESSED_BY_REDIRECT)) is None
        )

    def test_a_driver_that_cannot_be_read_is_unanswerable(self):
        """A driver fault is not a verdict about the session."""
        driver = _Driver([], raises=True)
        assert session_still_held(driver, session_signature(WITNESSED_YAKIMA)) is None

    def test_none_and_false_are_distinguishable_by_the_caller(self):
        held = _Driver(["igmAuth"])
        gone = _Driver(["_ga"])
        empty = session_signature(WITNESSED_BY_REDIRECT)
        real = session_signature(WITNESSED_YAKIMA)
        assert session_still_held(held, real) is True
        assert session_still_held(gone, real) is False
        assert session_still_held(gone, empty) is None


class TestTheFetchPathUsesIt:
    def _body(self, name: str) -> str:
        import inspect

        from src.crawler import ContentExtractor

        src = inspect.getsource(getattr(ContentExtractor, name))
        return "\n".join(
            line for line in src.splitlines() if not line.strip().startswith("#")
        )

    def test_confirm_session_names_all_four_answers(self):
        body = self._body("_confirm_session")
        for answer in ("not_applicable", "verified", "lapsed", "unverifiable"):
            assert f'"{answer}"' in body

    def test_unverifiable_is_not_reported_as_lapsed(self):
        """The distinction that keeps etype and auth0 fetchable."""
        body = self._body("_confirm_session")
        assert "if held is None:" in body
        assert body.index("held is None") < body.index('"verified" if held')

    def test_the_row_records_how_it_knows(self):
        """`authenticated_session` and `session_confirmed` are different claims.

        One says this driver logged in for this host; the other says the session
        was still held at THIS fetch.
        """
        from pathlib import Path

        crawler = Path("src/crawler/__init__.py").read_text()
        assert '"session_confirmed": self._confirm_session(driver, url)' in crawler
        assert '"authenticated_session": self._session_state(url)' in crawler

    def test_a_lapsed_session_is_asked_about_before_the_body(self):
        """Affirmative first, inference second.

        The body cannot answer whether the login dropped, so consulting it first
        would let a short real article be read as a lapse and a lapse be read as a
        short article.
        """
        body = self._body("_navigate_with_human_behavior")
        assert 'self._confirm_session(driver, url) == "lapsed"' in body
        assert body.index("_confirm_session") < body.index(
            "_logged_in_page_withheld_the_story"
        )

    def test_it_signs_in_again_before_refusing(self):
        body = self._body("_navigate_with_human_behavior")
        relogin = body.index("_ensure_authenticated(driver, domain)")
        refuse = body.index('"session_lapsed"')
        assert relogin < refuse

    def test_it_refuses_after_one_failed_relogin(self):
        """Not a loop. A second lapse on the same fetch means the LOGIN is wrong,
        and retrying spends attempts at a publisher who is refusing us."""
        body = self._body("_navigate_with_human_behavior")
        assert body.count("_ensure_authenticated(driver, domain)") == 1
        assert '"session_lapsed"' in body

    def test_the_stale_domain_is_forgotten_before_signing_in_again(self):
        """`_ensure_authenticated` returns early for a host already in the set.

        Without discarding it first the re-login would be a no-op and the fetch
        would be refused on a session that could have been recovered.
        """
        body = self._body("_navigate_with_human_behavior")
        discard = body.index("_authenticated_domains.discard")
        relogin = body.index("_ensure_authenticated(driver, domain)")
        assert discard < relogin
