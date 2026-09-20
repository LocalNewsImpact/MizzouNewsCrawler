"""A cookie diff across two origins is not evidence.

`driver.get_cookies()` returns only what the CURRENT document's origin can
read. The witness took `before` on the login page and `after` wherever the
login happened to leave the browser, so for any login that navigates away the
two snapshots described different origins and their difference meant nothing.

Measured 2026-09-20, one run per host:

| host                   | path            | ended on                  | cookies seen |
| ---------------------- | --------------- | ------------------------- | ------------ |
| yakimaherald           | modal, on page  | the publisher's origin    | real session |
| union-bulletin         | modal, on page  | the publisher's origin    | real session |
| tdn                    | form, url       | wherever the POST went    | NONE         |
| pendoreillerivervalley | etype, url      | the login result page     | NONE         |
| spokesman              | auth0, redirect | myaccount.spokesman.com   | that origin's|

spokesman is the proof that the snapshot origin was the variable rather than
the site: `AWSALB@myaccount.spokesman.com` can only be read by a document on
`myaccount.spokesman.com`, so that is where the browser was standing.

Two consequences, both in this module:

1. Both snapshots are taken on the publisher's own origin, so "added" means
   "this origin now carries a cookie it did not before".
2. A load balancer or WAF cookie is not evidence of a session -- it is set for
   everyone -- but it looks like evidence in a diff. It is reported separately
   instead of counted.

The second one matters because of what it was about to be used for: a verifier
that judges a login unattended cannot tell `AWSALB` from a session cookie, and
`etype` already returns True having confirmed only that a form submitted.
"""

from __future__ import annotations

import inspect

from src.cli.commands import validate_login as vl


class TestInfrastructureIsNotEvidence:
    def test_the_five_cookies_spokesman_actually_returned_are_infrastructure(self):
        """Named from the real run, not from a list of plausible names."""
        observed = [
            "AWSALB@myaccount.spokesman.com",
            "AWSALBCORS@myaccount.spokesman.com",
            "incap_ses_351_2192278@spokesman.com",
            "nlbi_2192278@spokesman.com",
            "visid_incap_2192278@spokesman.com",
        ]
        session, infra = vl.partition_evidence(observed)
        assert session == []
        assert len(infra) == 5

    def test_a_real_session_cookie_is_kept(self):
        """The two Connext hosts' evidence must survive the filter."""
        observed = [
            "igmAuth@yakimaherald.com",
            "nxt_alng_YHR_YHRCONFIG_PROD@yakimaherald.com",
            "ConneXtpS_WWUB_WWUBCONFIG_PROD@union-bulletin.com",
        ]
        session, infra = vl.partition_evidence(observed)
        assert len(session) == 3
        assert infra == []

    def test_a_mixed_list_splits(self):
        session, infra = vl.partition_evidence(
            ["igmAuth@x.com", "AWSALB@x.com", "__cf_bm@x.com", "sessionid@x.com"]
        )
        assert session == ["igmAuth@x.com", "sessionid@x.com"]
        assert infra == ["AWSALB@x.com", "__cf_bm@x.com"]

    def test_it_does_not_swallow_a_name_that_merely_starts_similarly(self):
        """`ELB` anchors at the start, so a real cookie containing it is safe.

        Over-matching here silently deletes the evidence the tool exists to
        show, which is worse than showing an extra infrastructure cookie.
        """
        session, _ = vl.partition_evidence(["MEMBER_ELB_TOKEN@x.com", "user_ts@x.com"])
        assert session == ["MEMBER_ELB_TOKEN@x.com", "user_ts@x.com"]

    def test_both_returned_lists_are_sorted(self):
        session, infra = vl.partition_evidence(["z@x.com", "a@x.com", "AWSALB@x.com"])
        assert session == ["a@x.com", "z@x.com"]
        assert infra == ["AWSALB@x.com"]

    def test_an_empty_list_is_not_an_error(self):
        assert vl.partition_evidence([]) == ([], [])


class TestBothSnapshotsAreTakenOnTheOrigin:
    def _body(self) -> str:
        source = inspect.getsource(vl.witness)
        # Comments stripped: the explanation above the fix quotes the old
        # ordering, and an unstripped check would match the prose.
        return "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )

    def test_the_origin_is_visited_before_the_first_snapshot(self):
        body = self._body()
        visit = body.index("driver.get(origin)")
        before = body.index("cookies_before = first_party_cookies")
        assert visit < before

    def test_the_origin_is_visited_again_before_the_second_snapshot(self):
        body = self._body()
        after = body.index("cookies_after = first_party_cookies")
        # The second navigation sits between the login and the after-snapshot.
        login = body.index("ok = perform_login")
        return_trip = body.index("driver.get(origin)", login)
        assert login < return_trip < after

    def test_the_login_control_is_read_on_the_origin_both_times(self):
        """A visibility flip across two different pages is not a flip."""
        body = self._body()
        first_snapshot = body.index("cookies_before = first_party_cookies")
        trigger_before = body.index("trigger_before = _visible")
        login_nav = body.index('login_url = cfg.get("login_url")')
        # Read right after the origin snapshot, before the login page is opened.
        assert first_snapshot < trigger_before < login_nav

    def test_the_performance_log_is_drained_before_the_return_trip(self):
        """get_log consumes the buffer, so the return trip's own requests would
        otherwise be all that survived of the auth exchange."""
        body = self._body()
        drain = body.rindex("network_responses(driver.get_log")
        login = body.index("ok = perform_login")
        return_trip = body.index("driver.get(origin)", login)
        assert drain < return_trip

    def test_a_failed_return_trip_is_reported_not_swallowed(self):
        body = self._body()
        assert "returned_to_origin" in body
        # Reported rather than raised: a login that worked should not be thrown
        # away because the last navigation failed.
        assert "return {" not in body[body.index("returned_to_origin = True") :][:200]


class TestTheReportSaysWhatIsAndIsNotProof:
    def _printer(self) -> str:
        return inspect.getsource(vl.handle_validate_login_command)

    def test_infrastructure_is_labelled_as_not_evidence(self):
        assert "NOT evidence" in self._printer()

    def test_a_mechanism_yes_with_no_observable_change_is_called_out(self):
        """The etype case: True, and nothing changed on the origin."""
        printer = self._printer()
        assert "nothing changed on" in printer
        assert "Do not record this as witnessed" in printer

    def test_the_callout_fires_only_when_every_signal_is_absent(self):
        """A control flip alone is still evidence, so it must suppress the note."""
        printer = self._printer()
        assert 'evidence["trigger_visible_after"] is False' in printer

    def test_a_cross_origin_diff_warns(self):
        assert "proves nothing" in self._printer()


class TestWhatGetsStored:
    def test_the_origin_is_recorded_with_the_witness(self):
        """So a stored record can be read later without assuming same-origin.

        The two records written on 2026-09-20 predate this and carry no origin
        key, which is how they can be told apart from ones taken properly.
        """
        source = inspect.getsource(vl.record)
        assert '"origin": evidence.get("origin")' in source

    def test_infrastructure_cookies_are_stored_too(self):
        source = inspect.getsource(vl.record)
        assert '"infrastructure_cookies"' in source

    def test_no_cookie_value_is_ever_stored(self):
        """The fingerprint is a length. A value would be a credential."""
        source = inspect.getsource(vl.first_party_cookies)
        assert "f\"len={len(c.get('value', ''))}\"" in source
