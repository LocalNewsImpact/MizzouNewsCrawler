"""Tests for the proxy diagnostic script."""
import os
import sys
from unittest.mock import MagicMock, Mock, patch

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

# Import after path modification
from diagnose_proxy import (  # noqa: E402
    check_environment,
    test_proxied_request,
    test_proxy_connectivity,
    test_real_site,
)


def test_check_environment_with_all_vars(monkeypatch, caplog):
    """Test environment check when all variables are set."""
    monkeypatch.setenv('USE_ORIGIN_PROXY', '1')
    monkeypatch.setenv('ORIGIN_PROXY_URL', 'http://proxy.test:9999')
    monkeypatch.setenv('PROXY_USERNAME', 'testuser')
    monkeypatch.setenv('PROXY_PASSWORD', 'testpass')

    check_environment()

    # Check that function runs without error - specific format may vary
    # but password should be masked
    assert not any('testpass' in record.message for record in caplog.records)


def test_check_environment_with_no_vars(monkeypatch, caplog):
    """Test environment check when no variables are set."""
    monkeypatch.delenv('USE_ORIGIN_PROXY', raising=False)
    monkeypatch.delenv('ORIGIN_PROXY_URL', raising=False)
    monkeypatch.delenv('PROXY_USERNAME', raising=False)
    monkeypatch.delenv('PROXY_PASSWORD', raising=False)
    monkeypatch.delenv('NO_PROXY', raising=False)
    monkeypatch.delenv('no_proxy', raising=False)

    check_environment()

    # Check that warning about no vars is logged
    assert any(
        'No proxy environment variables' in record.message
        for record in caplog.records
    )


@patch('diagnose_proxy.requests.get')
def test_proxy_connectivity_success(mock_get, monkeypatch):
    """Test successful proxy connectivity."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = 'Proxy OK'
    mock_get.return_value = mock_response

    monkeypatch.setenv('ORIGIN_PROXY_URL', 'http://proxy.test:9999')

    # Should not raise
    test_proxy_connectivity()


@patch('diagnose_proxy.requests.get')
def test_proxy_connectivity_failure(mock_get, monkeypatch, caplog):
    """Test failed proxy connectivity."""
    import requests
    mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

    monkeypatch.setenv('ORIGIN_PROXY_URL', 'http://proxy.test:9999')

    test_proxy_connectivity()

    # Check that error is logged
    assert any('Cannot connect to proxy' in record.message for record in caplog.records)


# Note: Testing cloudscraper availability is complex due to import mechanisms
# The function test_cloudscraper() is tested via integration tests
# These unit tests focus on other diagnostic functions


@patch('diagnose_proxy.requests.Session')
@patch('diagnose_proxy.enable_origin_proxy')
def test_proxied_request_success(mock_enable, mock_session, monkeypatch):
    """Test successful proxied request."""
    mock_session_instance = MagicMock()
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = '{"origin": "1.2.3.4"}'
    mock_session_instance.get.return_value = mock_response
    mock_session.return_value = mock_session_instance

    monkeypatch.setenv('USE_ORIGIN_PROXY', '1')

    test_proxied_request()


@patch('diagnose_proxy.requests.Session')
@patch('diagnose_proxy.enable_origin_proxy')
def test_proxied_request_disabled(mock_enable, mock_session, monkeypatch, caplog):
    """Test behavior when proxy is disabled."""
    monkeypatch.delenv('USE_ORIGIN_PROXY', raising=False)

    test_proxied_request()

    # Check that warning is logged
    proxy_not_enabled = any(
        'USE_ORIGIN_PROXY is not enabled' in record.message
        for record in caplog.records
    )
    assert proxy_not_enabled


@patch('diagnose_proxy.requests.Session')
@patch('diagnose_proxy.enable_origin_proxy')
def test_proxied_request_error(mock_enable, mock_session, monkeypatch, caplog):
    """Test error during proxied request."""
    import requests
    mock_session_instance = MagicMock()
    error = requests.exceptions.ConnectionError("Failed")
    mock_session_instance.get.side_effect = error
    mock_session.return_value = mock_session_instance

    monkeypatch.setenv('USE_ORIGIN_PROXY', '1')

    test_proxied_request()

    # Check that error is logged
    assert any('Connection error' in record.message for record in caplog.records)


@patch('diagnose_proxy.requests.Session')
@patch('diagnose_proxy.enable_origin_proxy')
def test_real_site_success(mock_enable, mock_session, monkeypatch):
    """Test successful real site fetch."""
    mock_session_instance = MagicMock()
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = '<html>Test</html>'
    mock_session_instance.get.return_value = mock_response
    mock_session.return_value = mock_session_instance

    monkeypatch.setenv('USE_ORIGIN_PROXY', '1')

    test_real_site()


@patch('diagnose_proxy.requests.Session')
@patch('diagnose_proxy.enable_origin_proxy')
def test_real_site_captcha_detection(mock_enable, mock_session, monkeypatch, caplog):
    """Test CAPTCHA detection in real site test."""
    mock_session_instance = MagicMock()
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = '<html>Please complete the CAPTCHA</html>'
    mock_session_instance.get.return_value = mock_response
    mock_session.return_value = mock_session_instance

    monkeypatch.setenv('USE_ORIGIN_PROXY', '1')

    test_real_site()

    # Check that CAPTCHA warning is logged
    assert any('CAPTCHA detected' in record.message for record in caplog.records)


@patch('diagnose_proxy.requests.Session')
@patch('diagnose_proxy.enable_origin_proxy')
def test_real_site_cloudflare_detection(mock_enable, mock_session, monkeypatch, caplog):
    """Test Cloudflare detection in real site test."""
    mock_session_instance = MagicMock()
    mock_response = Mock()
    mock_response.status_code = 503
    mock_response.text = '<html>Cloudflare protection</html>'
    mock_session_instance.get.return_value = mock_response
    mock_session.return_value = mock_session_instance

    monkeypatch.setenv('USE_ORIGIN_PROXY', '1')

    test_real_site()

    # Check that Cloudflare warning is logged
    cloudflare_detected = any(
        'Cloudflare protection detected' in record.message
        for record in caplog.records
    )
    assert cloudflare_detected


@patch('diagnose_proxy.requests.Session')
@patch('diagnose_proxy.enable_origin_proxy')
def test_real_site_bot_detection(mock_enable, mock_session, monkeypatch, caplog):
    """Test bot detection (403) in real site test."""
    mock_session_instance = MagicMock()
    mock_response = Mock()
    mock_response.status_code = 403
    mock_response.text = '<html>Access denied</html>'
    mock_session_instance.get.return_value = mock_response
    mock_session.return_value = mock_session_instance

    monkeypatch.setenv('USE_ORIGIN_PROXY', '1')

    test_real_site()

    # Check that bot detection error is logged
    assert any('Bot detection' in record.message for record in caplog.records)
