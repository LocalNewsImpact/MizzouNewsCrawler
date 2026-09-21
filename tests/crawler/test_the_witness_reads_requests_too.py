"""A redirect and a request body are where two vendors keep their proof.

Chrome does not emit `Network.responseReceived` for a 3xx. The redirect's status
arrives as `redirectResponse` inside the NEXT `Network.requestWillBeSent`. So a
reader of responses alone is blind to every redirect -- which is how
`POST /account/etype-login -> 302 -> /account/etype-auth`, the one signal that
proves an eType login worked, stayed invisible while the login was reported as
succeeding.

eType needs it more than any other vendor. Its session cookie (`tipssid`) exists
BEFORE the login and the server upgrades it in place, so no cookie diff can ever
show anything -- confirmed from the request headers of a real manual login on
2026-09-20. The 302 is the only evidence there is.

The request body is where Auth0 keeps the `realm`. `Username-Password-
Authentication` worked on the spokesman tenant because it is Auth0's default, not
because we knew it; for any other publisher it has to be observed. It is posted to
`/usernamepassword/login` and appears nowhere in a URL.

Which makes the safety property the first thing tested here: a login body carries
the subscriber's PASSWORD. `BODY_FIELDS_WORTH_READING` is an allowlist, and being
an allowlist rather than a filter applied afterwards is the point. On 2026-09-20 a
log level of DEBUG printed a subscriber password into a pod log, with nobody
reading request bodies at all.
"""

from __future__ import annotations

import json

from src.crawler.browser_status import (
    BODY_FIELDS_WORTH_READING,
    network_redirects,
    network_responses,
    request_body_fields,
)


def _entry(method: str, params: dict) -> dict:
    """One line of a Chrome performance log."""
    return {"message": json.dumps({"message": {"method": method, "params": params}})}


def _request(url: str, post: str | None = None, redirect: dict | None = None) -> dict:
    params: dict = {"request": {"url": url, "method": "POST" if post else "GET"}}
    if post is not None:
        params["request"]["postData"] = post
    if redirect is not None:
        params["redirectResponse"] = redirect
    return _entry("Network.requestWillBeSent", params)


def _response(url: str, status: int) -> dict:
    return _entry(
        "Network.responseReceived", {"response": {"url": url, "status": status}}
    )


ETYPE_LOGIN = "https://www.pendoreillerivervalley.com/account/etype-login"
AUTH0_LOGIN = "https://login.spokesman.com/usernamepassword/login"

#: A real login body shape. The password here must never appear in any output.
SECRET = "hunter2-do-not-leak"
AUTH0_BODY = (
    "client_id=q2DzLa&realm=Username-Password-Authentication"
    f"&username=jody.brannon%40wsu.edu&password={SECRET}"
    "&scope=openid+profile+email+offline_access&tenant=spokesman"
)


class TestAPasswordCannotEscape:
    def test_the_password_is_not_in_the_result(self):
        found = request_body_fields([_request(AUTH0_LOGIN, post=AUTH0_BODY)])
        assert found, "nothing was read at all"
        assert SECRET not in json.dumps(found)

    def test_no_credential_key_survives(self):
        """Asserted on the FIELDS, not on a dump of the whole result.

        The endpoint is `/usernamepassword/login`, so "username" and "password"
        both appear in the URL as a matter of Auth0's path naming. A substring
        check over the serialised result therefore fails on the endpoint name and
        proves nothing about the body -- the first version of this test did exactly
        that.
        """
        found = request_body_fields([_request(AUTH0_LOGIN, post=AUTH0_BODY)])
        for _url, fields in found:
            for key, value in fields.items():
                assert key not in ("username", "password", "email")
                assert SECRET not in value
                assert "jody.brannon" not in value

    def test_the_url_is_kept_even_though_it_is_named_after_credentials(self):
        """The endpoint name is the useful part: it says which Auth0 flow ran."""
        found = request_body_fields([_request(AUTH0_LOGIN, post=AUTH0_BODY)])
        assert found[0][0] == AUTH0_LOGIN

    def test_an_unknown_key_is_not_carried(self):
        """An allowlist, so a vendor inventing `secret_answer` is safe by default.

        This is why it is an allowlist and not a denylist of known-bad names: the
        set of things a publisher might post is not enumerable.
        """
        found = request_body_fields(
            [_request(AUTH0_LOGIN, post="realm=x&secret_answer=my-mothers-maiden-name")]
        )
        assert found == [(AUTH0_LOGIN, {"realm": "x"})]

    def test_every_allowlisted_key_is_one_a_login_needs_again(self):
        """No key here is a credential. Stated so adding one is a deliberate act."""
        for key in BODY_FIELDS_WORTH_READING:
            assert key not in ("username", "password", "email", "pass", "token")

    def test_a_long_value_is_truncated(self):
        """A JWT posted under an allowlisted name must not be stored whole."""
        found = request_body_fields([_request(AUTH0_LOGIN, post="scope=" + "x" * 400)])
        assert len(found[0][1]["scope"]) <= 120


class TestTheRealmIsReadable:
    def test_the_realm_comes_out_of_the_body(self):
        found = request_body_fields([_request(AUTH0_LOGIN, post=AUTH0_BODY)])
        url, fields = found[0]
        assert url == AUTH0_LOGIN
        assert fields["realm"] == "Username-Password-Authentication"

    def test_the_other_grant_parameters_come_too(self):
        _, fields = request_body_fields([_request(AUTH0_LOGIN, post=AUTH0_BODY)])[0]
        assert fields["client_id"] == "q2DzLa"
        assert fields["tenant"] == "spokesman"
        assert "openid" in fields["scope"]

    def test_url_encoding_is_undone(self):
        found = request_body_fields(
            [_request(AUTH0_LOGIN, post="realm=Username-Password-Authentication+2")]
        )
        assert found[0][1]["realm"] == "Username-Password-Authentication 2"

    def test_a_get_with_no_body_yields_nothing(self):
        assert request_body_fields([_request(ETYPE_LOGIN)]) == []


class TestARedirectIsVisible:
    def test_the_etype_302_is_reported(self):
        """The proof, from the real exchange the publisher's own headers showed."""
        log = [
            _response(ETYPE_LOGIN, 200),  # the GET of the login page
            _request(
                "https://www.pendoreillerivervalley.com/account/etype-auth",
                redirect={"url": ETYPE_LOGIN, "status": 302},
            ),
        ]
        assert network_redirects(log) == [(302, ETYPE_LOGIN)]

    def test_responses_alone_never_show_it(self):
        """The bug, stated as a property: this is why the reader had to be added."""
        log = [
            _request(
                "https://www.pendoreillerivervalley.com/account/etype-auth",
                redirect={"url": ETYPE_LOGIN, "status": 302},
            )
        ]
        assert network_redirects(log) == [(302, ETYPE_LOGIN)]
        assert network_responses(log) == []

    def test_the_url_reported_is_the_one_redirected_not_the_destination(self):
        """The status belongs to the request that was answered with the 3xx."""
        log = [
            _request(
                "https://example.com/after",
                redirect={"url": "https://example.com/before", "status": 301},
            )
        ]
        assert network_redirects(log) == [(301, "https://example.com/before")]

    def test_a_request_with_no_redirect_is_not_a_redirect(self):
        assert network_redirects([_request(ETYPE_LOGIN, post="realm=x")]) == []

    def test_a_malformed_entry_is_skipped_rather_than_raising(self):
        """A witness must not die because one log line is unparseable."""
        log = [{"message": "not json"}, {}, _request(ETYPE_LOGIN)]
        assert network_redirects(log) == []
        assert request_body_fields(log) == []

    def test_an_empty_log_is_empty(self):
        for reader in (network_redirects, request_body_fields, network_responses):
            assert reader([]) == []
            assert reader(None) == []
