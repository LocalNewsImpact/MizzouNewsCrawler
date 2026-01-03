import os
from unittest.mock import MagicMock, Mock, patch

import pytest
from selenium.webdriver.common.by import By

from src.crawler import ContentExtractor


class TestPerimeterXBypass:
    def test_detect_captcha_or_challenge_perimeterx(self):
        """Test that PerimeterX specific indicators are detected."""
        extractor = ContentExtractor()
        mock_driver = Mock()

        # Test keyword detection
        mock_driver.page_source = "<html><body>Pardon our interruption... press and hold to verify</body></html>"
        mock_driver.find_elements.return_value = []
        assert extractor._detect_captcha_or_challenge(mock_driver) is True

        # Test element detection
        mock_driver.page_source = "<html><body>Some other content</body></html>"
        mock_driver.find_elements.side_effect = lambda by, sel: (
            [Mock()] if sel == "#px-captcha" else []
        )
        assert extractor._detect_captcha_or_challenge(mock_driver) is True

    def test_navigate_order_challenge_before_subscription(self):
        """Test that bot challenges are checked before subscription walls."""
        extractor = ContentExtractor()
        mock_driver = Mock()

        # Mock navigation and stabilization
        with (
            patch("src.crawler.WebDriverWait"),
            patch("src.crawler.EC"),
            patch("time.sleep"),
        ):

            # We want to verify the call order:
            # 1. _detect_captcha_or_challenge
            # 2. _try_close_modals (which might call _detect_subscription_wall)
            # 3. _detect_subscription_wall

            with (
                patch.object(
                    extractor, "_detect_captcha_or_challenge"
                ) as mock_detect_challenge,
                patch.object(extractor, "_detect_subscription_wall") as mock_detect_sub,
                patch.object(extractor, "_try_close_modals") as mock_close_modals,
            ):

                # Setup call order tracking
                manager = MagicMock()
                manager.attach_mock(mock_detect_challenge, "detect_challenge")
                manager.attach_mock(mock_close_modals, "close_modals")
                manager.attach_mock(mock_detect_sub, "detect_sub")

                mock_detect_challenge.return_value = False
                mock_close_modals.return_value = False
                mock_detect_sub.return_value = False

                extractor._navigate_with_human_behavior(
                    mock_driver, "https://example.com"
                )

                # Verify order: challenge -> modals -> sub
                # Note: _try_close_modals is called before _detect_subscription_wall
                call_names = [call[0] for call in manager.mock_calls]

                # Filter out noise if any
                relevant_calls = [
                    name
                    for name in call_names
                    if name in ("detect_challenge", "close_modals", "detect_sub")
                ]

                assert relevant_calls[0] == "detect_challenge"
                assert "close_modals" in relevant_calls
                assert relevant_calls[-1] == "detect_sub"

    def test_try_bypass_challenge_perimeterx_long_press(self):
        """Test the long-press bypass logic for PerimeterX."""
        extractor = ContentExtractor()
        mock_driver = Mock()

        # Mock the "Press and Hold" button
        mock_button = Mock()
        mock_button.is_displayed.return_value = True
        mock_button.is_enabled.return_value = True

        # Only return the button for the px-captcha selector
        def mock_find_elements(by, selector):
            if selector == "#px-captcha":
                return [mock_button]
            return []

        mock_driver.find_elements.side_effect = mock_find_elements

        with patch(
            "selenium.webdriver.common.action_chains.ActionChains"
        ) as mock_actions:
            # Mock successful bypass
            # We need to mock the chain of calls: click_and_hold().pause().release().perform()
            mock_chain = mock_actions.return_value
            mock_chain.click_and_hold.return_value = mock_chain
            mock_chain.pause.return_value = mock_chain
            mock_chain.release.return_value = mock_chain

            # Mock detection to return True then False (bypassed)
            with patch.object(
                extractor, "_detect_captcha_or_challenge", side_effect=[True, False]
            ):
                result = extractor._try_bypass_challenge(
                    mock_driver, "https://example.com"
                )

            assert result is True
            # click_and_hold is called without arguments because we moved to the element first
            mock_chain.click_and_hold.assert_called_once()
            assert mock_chain.perform.called

    def test_mark_domain_special_extraction_perimeterx(self):
        """Test that perimeterx protection type maps to selenium method."""
        extractor = ContentExtractor()

        with patch("src.models.database.DatabaseManager") as mock_db_mgr:
            mock_session = MagicMock()
            mock_db_mgr.return_value.get_session.return_value.__enter__.return_value = (
                mock_session
            )

            extractor._mark_domain_special_extraction("example.com", "perimeterx")

            # Verify the SQL update used 'selenium'
            # session.execute(text(...), params_dict)
            args, kwargs = mock_session.execute.call_args
            params = args[1] if len(args) > 1 else kwargs.get("params")
            assert params["method"] == "selenium"
            assert params["is_selenium"] is True
            assert params["protection_type"] == "perimeterx"

    def test_detect_subscription_wall_excludes_perimeterx(self):
        """Test that subscription wall detection doesn't trigger on PerimeterX pages."""
        extractor = ContentExtractor()
        mock_driver = Mock()

        # Page has "subscribe" (paywall keyword) but also "press and hold" (challenge)
        mock_driver.page_source = "<html><body>Please subscribe to continue... press and hold to verify you are human</body></html>"

        # _detect_captcha_or_challenge should be True
        assert extractor._detect_captcha_or_challenge(mock_driver) is True

        # _detect_subscription_wall should be False because it should check for challenges first
        assert extractor._detect_subscription_wall(mock_driver) is False

    def test_headful_mode_respected(self):
        """Test that SELENIUM_EXECUTION_MODE=headful is correctly identified."""
        with patch.dict(os.environ, {"SELENIUM_EXECUTION_MODE": "headful"}):
            extractor = ContentExtractor()
            assert extractor.selenium_mode == "headful"
            assert extractor._is_headless_selenium_mode() is False

        with patch.dict(os.environ, {"SELENIUM_EXECUTION_MODE": "headless"}):
            extractor = ContentExtractor()
            assert extractor.selenium_mode == "headless"
            assert extractor._is_headless_selenium_mode() is True
