"""A credentialed fetch keeps the ad networks blocked from login to article.

#715 blocked the ad networks for the login and lifted the block when the login
finished. The article fetch after it then froze: on a Wenatchee World article,
2026-10-14, ten idle seconds after window.stop() took the proxy relay from 101
to 287 connections and a cookie read to 39.3s -- past the 30s client timeout --
so the session check after navigation hung and the story was filed
not_article. With the ads blocked: 12 connections, 0.2s.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from src.crawler import ContentExtractor
from src.crawler import authenticated_login as al


def _lifts(driver) -> bool:
    return any(
        c.args == ("Network.setBlockedURLs", {"urls": []})
        for c in driver.execute_cdp_cmd.call_args_list
    )


class TestTheLoginLeavesAnExistingBlockInPlace:
    def test_a_block_set_before_the_login_survives_it(self):
        driver = MagicMock()
        assert al.block_ad_traffic(driver) is True
        with al.ad_traffic_blocked(driver):
            pass
        assert not _lifts(driver)
        assert al.ad_traffic_is_blocked(driver)

    def test_a_block_the_login_set_is_lifted_after_it(self):
        driver = MagicMock()
        with al.ad_traffic_blocked(driver):
            assert al.ad_traffic_is_blocked(driver)
        assert _lifts(driver)
        assert not al.ad_traffic_is_blocked(driver)

    def test_a_driver_that_was_never_blocked_reads_as_unblocked(self):
        assert al.ad_traffic_is_blocked(MagicMock()) is False


def test_the_credentialed_fetch_blocks_before_it_signs_in_and_navigates():
    source = inspect.getsource(ContentExtractor._extract_with_selenium)
    blocked = source.index("block_ad_traffic(driver)")
    assert source.index("if self._requires_login(urlparse(url).netloc):") < blocked
    assert blocked < source.index("self._ensure_authenticated(driver")
    assert blocked < source.index("self._navigate_with_human_behavior(driver, url)")
