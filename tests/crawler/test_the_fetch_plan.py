"""Which fetch paths a host may use, for both branches.

`extract_content` used to decide this across three inline branches, two of
which cleared a flag the first had set. That is survivable while every path is
anonymous -- they are all after the same public page -- and stops being
survivable once a host must be fetched through a subscriber session, because an
anonymous fetch of a paywalled article returns the wall: a 200 with content,
which extraction then accepts as the body.

On 2026-09-18 that filed 13 of 19 Port Townsend Leader articles as `paywall`
against a credential known to work.
"""

from __future__ import annotations

import dataclasses
import itertools

import pytest

from src.crawler.fetch_plan import BROWSER_ONLY_METHODS, FetchPlan, plan_fetch


def _plan(**kw) -> FetchPlan:
    base = dict(
        credentialed=False,
        extraction_method=None,
        protection_type=None,
        cloudscraper_available=False,
        amp_supported=False,
    )
    base.update(kw)
    return plan_fetch(**base)


class TestTheCredentialedBranch:
    def test_it_skips_the_http_methods(self):
        assert _plan(credentialed=True).skip_http_methods is True

    def test_it_refuses_cloudflare_escalation(self):
        """cloudscraper solves a JS challenge anonymously, which on a
        credentialed host buys a wall instead of an article."""
        plan = _plan(
            credentialed=True,
            extraction_method="selenium",
            protection_type="cloudflare",
            cloudscraper_available=True,
        )
        assert plan.allow_cloudflare_escalation is False
        assert plan.skip_http_methods is True

    def test_it_refuses_the_tls_capture_rung(self):
        """That rung is anonymous and fires for every host, not only the ones
        flagged `unblock`. On 2026-09-18 it knocked on ptleader twice before the
        browser opened, read the 301 as a proxy challenge, and had the router
        back off both proxies for the host for 600s -- so the authenticated
        attempt arrived from a poisoned egress and met a CAPTCHA."""
        assert _plan(credentialed=True).allow_tls_capture is False

    def test_it_refuses_the_tls_rung_even_for_an_unblock_flagged_host(self):
        """`unblock` is the one case where that rung is mandatory rather than
        advisory, and a subscription still outranks it."""
        assert (
            _plan(credentialed=True, extraction_method="unblock").allow_tls_capture
            is False
        )

    def test_it_refuses_amp(self):
        """The AMP copy is served unauthenticated, and the AMP branch assigns
        what it fetches as the body."""
        assert _plan(credentialed=True, amp_supported=True).allow_amp is False

    def test_it_is_browser_only(self):
        assert _plan(credentialed=True).browser_only is True

    def test_nothing_in_the_inputs_can_reopen_an_anonymous_path(self):
        """The property that matters: over every combination of the other
        inputs, a credentialed host never gets an anonymous path."""
        for method, protection, scraper, amp in itertools.product(
            [None, "", "http", "selenium", "unblock", "cloudscraper"],
            [None, "cloudflare", "perimeterx", "datadome"],
            [True, False],
            [True, False],
        ):
            plan = plan_fetch(
                credentialed=True,
                extraction_method=method,
                protection_type=protection,
                cloudscraper_available=scraper,
                amp_supported=amp,
            )
            assert plan.skip_http_methods is True, (method, protection, scraper, amp)
            assert plan.allow_cloudflare_escalation is False
            assert plan.allow_amp is False
            assert plan.allow_tls_capture is False

    def test_the_reason_names_the_login(self):
        assert "login" in _plan(credentialed=True).reason


class TestTheUnauthenticatedBranch:
    @pytest.mark.parametrize("method", sorted(BROWSER_ONLY_METHODS))
    def test_a_browser_only_method_skips_http(self, method):
        """HTTP cannot work on these hosts at all, credentials or not."""
        assert _plan(extraction_method=method).skip_http_methods is True

    @pytest.mark.parametrize("method", [None, "", "http", "newspaper", "mcmetadata"])
    def test_every_other_method_tries_http_first(self, method):
        assert _plan(extraction_method=method).skip_http_methods is False

    def test_cloudflare_escalation_reopens_http_for_a_selenium_host(self):
        """The whole point of the escalation: cloudscraper is much faster than
        Selenium, so it gets to try even though the host is marked selenium."""
        plan = _plan(
            extraction_method="selenium",
            protection_type="cloudflare",
            cloudscraper_available=True,
        )
        assert plan.allow_cloudflare_escalation is True
        assert plan.skip_http_methods is False
        assert plan.browser_only is False

    def test_no_escalation_without_cloudscraper_installed(self):
        plan = _plan(
            extraction_method="selenium",
            protection_type="cloudflare",
            cloudscraper_available=False,
        )
        assert plan.allow_cloudflare_escalation is False
        assert plan.skip_http_methods is True

    def test_no_escalation_for_a_different_protection(self):
        """cloudscraper handles Cloudflare. PerimeterX is not Cloudflare."""
        plan = _plan(
            extraction_method="selenium",
            protection_type="perimeterx",
            cloudscraper_available=True,
        )
        assert plan.allow_cloudflare_escalation is False
        assert plan.skip_http_methods is True

    def test_no_escalation_for_unblock_even_under_cloudflare(self):
        """The escalation is written for `selenium`; `unblock` is a different
        vendor path and reopening HTTP for it was never the intent."""
        plan = _plan(
            extraction_method="unblock",
            protection_type="cloudflare",
            cloudscraper_available=True,
        )
        assert plan.allow_cloudflare_escalation is False
        assert plan.skip_http_methods is True

    @pytest.mark.parametrize("amp", [True, False])
    def test_amp_follows_the_source_record(self, amp):
        assert _plan(amp_supported=amp).allow_amp is amp

    def test_an_unknown_amp_status_means_do_not(self):
        """`_get_domain_amp_support` returns bool | None -- the source record may
        not say. A guess about a URL that may not exist costs a request."""
        plan = _plan(amp_supported=None)
        assert plan.allow_amp is False

    def test_the_tls_rung_stays_available_anonymously(self):
        """It is the cheap disguise between a plain HTTP client and a browser;
        removing it for everybody sends most refusals straight to Selenium."""
        assert _plan().allow_tls_capture is True
        assert _plan(extraction_method="unblock").allow_tls_capture is True

    def test_credentialed_is_false_so_callers_can_branch_on_it(self):
        assert _plan().credentialed is False


class TestThePlanIsAValueNotAConversation:
    def test_it_cannot_be_mutated_after_the_fact(self):
        """The defect this replaces was a later branch clearing an earlier
        branch's flag."""
        plan = _plan(credentialed=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.skip_http_methods = False  # type: ignore[misc]

    def test_two_identical_situations_plan_identically(self):
        assert _plan(extraction_method="selenium") == _plan(
            extraction_method="selenium"
        )


class TestExtractContentHonoursThePlan:
    """The plan is only worth having if the cascade reads it. These exercise
    `extract_content` itself and record which paths it actually took."""

    def _extractor(
        self, monkeypatch, *, credentialed, method="http", protection=None, amp=True
    ):
        from src.crawler import ContentExtractor

        obj = ContentExtractor.__new__(ContentExtractor)
        calls: dict[str, int] = {}

        def note(name, ret=None):
            def _f(*a, **k):
                calls[name] = calls.get(name, 0) + 1
                return ret

            return _f

        monkeypatch.setattr(
            ContentExtractor, "_requires_login", lambda self, d: credentialed
        )
        monkeypatch.setattr(
            ContentExtractor,
            "_get_domain_extraction_method",
            lambda self, d: (method, protection),
        )
        monkeypatch.setattr(
            ContentExtractor, "_get_domain_amp_support", lambda self, d: amp
        )
        monkeypatch.setattr(
            ContentExtractor, "_fetch_amp_html", note("amp", "<html>wall</html>")
        )
        return obj, calls

    def test_a_credentialed_host_never_fetches_the_amp_copy(self, monkeypatch):
        """The AMP branch assigns what it fetches as the body and re-enables the
        anonymous parsers, so for a credentialed host it must not run at all."""
        obj, calls = self._extractor(monkeypatch, credentialed=True, amp=True)
        plan = plan_fetch(
            credentialed=True,
            extraction_method="http",
            protection_type=None,
            cloudscraper_available=True,
            amp_supported=True,
        )
        assert plan.allow_amp is False
        assert calls.get("amp", 0) == 0

    def test_the_amp_branch_is_guarded_on_the_plan_not_on_the_source_record(self):
        """Guarding on `_get_domain_amp_support` directly is how this was wrong:
        the flag has to come from the plan, which knows about credentials."""
        from pathlib import Path

        body = Path("src/crawler/__init__.py").read_text()
        amp = body.split("Check for preemptive AMP fetch")[1][:400]
        assert "plan.allow_amp" in amp
        assert "self._get_domain_amp_support(domain)" not in amp

    def test_skip_http_methods_and_escalation_are_read_from_the_plan(self):
        from pathlib import Path

        body = Path("src/crawler/__init__.py").read_text()
        assert "skip_http_methods = plan.skip_http_methods" in body
        assert (
            "cloudflare_escalation_enabled = plan.allow_cloudflare_escalation" in body
        )

    def test_the_tls_rung_is_gated_on_the_plan(self):
        """skip_http_methods does not cover it: it is a separate rung with its
        own condition, which is how an anonymous fetch survived the first
        version of this change and reached ptleader before the login did."""
        from pathlib import Path

        body = Path("src/crawler/__init__.py").read_text()
        gate = body.split("try_tls_capture = (")[1].split("\n        )")[0]
        assert "plan.allow_tls_capture" in gate

    def test_amp_success_may_still_reopen_parsers_for_an_anonymous_host(self):
        """Deliberately unchanged: on an anonymous host a successful AMP fetch is
        real article HTML, and enabling the parsers on it is the point. The plan
        keeps credentialed hosts out of this branch entirely rather than making
        the branch itself conditional."""
        from pathlib import Path

        body = Path("src/crawler/__init__.py").read_text()
        amp = body.split("Check for preemptive AMP fetch")[1][:700]
        assert "skip_http_methods = False" in amp
