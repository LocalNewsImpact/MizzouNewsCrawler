"""A login runs with the ad networks blocked, and the block is lifted after.

chinookobserver.com, 2026-10-14, reproduced in a production crawler pod: the
driver loads at DOMContentLoaded (page_load_strategy='eager') and the ad
auction keeps going. In eight idle seconds the proxy relay went from 69 to 366
connections, and the next chromedriver command -- a cookie read, a script --
waited out the 30s client timeout: `DriverUnresponsive`. Back-to-back loads
never showed it; the wait a login makes for its control to render did.

`window.stop()` cured the hang but also stopped Connext before it revealed the
login control. Blocking the ad networks kept the page alive for 16 idle seconds
at 11-35 connections with the control shown.
"""

from __future__ import annotations

import fnmatch
import inspect
from unittest.mock import MagicMock

import pytest

from src.cli.commands import validate_login as vl
from src.crawler import authenticated_login as al


def _blocked(url: str) -> bool:
    return any(fnmatch.fnmatchcase(url, p) for p in al.AD_NETWORK_PATTERNS)


class TestThePatterns:
    @pytest.mark.parametrize(
        "url",
        [
            "https://fastlane.rubiconproject.com/a/api/fastlane.json",
            "https://direct.adsrvr.org/bid/bidder/x",
            "https://prebid.media.net/rtb/prebid",
            "https://rtb.openx.net/openrtbb/prebidjs",
            "https://securepubads.g.doubleclick.net/gampad/ads",
            "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js",
            "https://c.amazon-adsystem.com/aax2/apstag.js",
        ],
    )
    def test_the_measured_ad_traffic_is_blocked(self, url):
        assert _blocked(url)

    @pytest.mark.parametrize(
        "url",
        [
            # the publishers themselves
            "https://chinookobserver.com/",
            "https://www.wenatcheeworld.com/users/login/",
            "https://www.cascadiadaily.com/log-in/",
            # login vendors
            "https://auth.mcclatchy.com/u/login/identifier",
            "https://login.spokesman.com/authorize",
            "https://cdn.mg2connext.com/prod/ConneXt.js",
            "https://id.tinypass.com/id/api/v1/identity/login",
            "https://ptleader.com/login/",
            "https://www.pendoreillerivervalley.com/account/etype-login",
            # consent
            "https://cmp.osano.com/XFMmWwALPB/osano.js",
            # a host that merely contains an ad network's name
            "https://www.multimedia.net/story",
        ],
    )
    def test_nothing_a_login_needs_is_blocked(self, url):
        assert not _blocked(url)


class TestTheBlock:
    def test_it_is_set_for_the_login_and_lifted_after(self):
        driver = MagicMock()
        with al.ad_traffic_blocked(driver):
            set_call = driver.execute_cdp_cmd.call_args_list[-1]
            assert set_call.args[0] == "Network.setBlockedURLs"
            assert set_call.args[1]["urls"] == list(al.AD_NETWORK_PATTERNS)
        assert driver.execute_cdp_cmd.call_args_list[-1].args == (
            "Network.setBlockedURLs",
            {"urls": []},
        )

    def test_it_is_lifted_when_the_login_raises(self):
        driver = MagicMock()
        with pytest.raises(RuntimeError):
            with al.ad_traffic_blocked(driver):
                raise RuntimeError("login blew up")
        assert driver.execute_cdp_cmd.call_args_list[-1].args == (
            "Network.setBlockedURLs",
            {"urls": []},
        )

    def test_a_driver_without_cdp_logs_in_unblocked(self):
        driver = MagicMock()
        driver.execute_cdp_cmd.side_effect = RuntimeError("no CDP")
        assert al.block_ad_traffic(driver) is False
        with al.ad_traffic_blocked(driver):
            pass  # no raise, and nothing to lift


class TestPerformLogin:
    @pytest.mark.parametrize("outcome", [True, False])
    def test_the_mechanism_runs_with_the_ads_blocked(self, monkeypatch, outcome):
        driver = MagicMock()
        seen = {}

        def fake_form(drv, cfg, user, pw):
            seen["urls"] = drv.execute_cdp_cmd.call_args_list[-1].args[1]["urls"]
            return outcome

        monkeypatch.setattr(al, "_login_form", fake_form)
        assert (
            al.perform_login(
                driver, auth_type="form", auth_config={}, username="u", password="p"
            )
            is outcome
        )
        assert seen["urls"] == list(al.AD_NETWORK_PATTERNS)
        assert driver.execute_cdp_cmd.call_args_list[-1].args[1] == {"urls": []}


class TestTheWitness:
    def _body(self):
        return "\n".join(
            line
            for line in inspect.getsource(vl.witness).splitlines()
            if not line.strip().startswith("#")
        )

    def test_it_blocks_before_the_first_page_load(self):
        body = self._body()
        assert body.index("block_ad_traffic(driver)") < body.index(
            "arrive(driver, origin)"
        )

    def test_every_step_is_timed(self):
        body = self._body()
        for step in ("open origin", "open login page", "login", "return to origin"):
            assert f'_step("{step}"' in body
