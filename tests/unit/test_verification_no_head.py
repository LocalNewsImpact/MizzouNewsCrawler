from unittest.mock import MagicMock, patch

from src.services.url_verification import URLVerificationService


class NoHeadSession:
    def __init__(self):
        self.headers = {}

    def head(self, *a, **kw):
        raise RuntimeError("HEAD should not be called")


class DummySniffer:
    def __init__(self):
        self.called = False

    def guess(self, url):
        self.called = True
        return True


def test_verification_uses_storysniffer_and_no_head(monkeypatch):
    """Test that URLVerificationService uses StorySniffer without making HEAD requests.

    This is a unit test - it should not require a live database connection.
    Mock the telemetry system and DatabaseManager to isolate the verification logic.
    """
    # Mock the telemetry tracker to avoid database initialization
    mock_telemetry = MagicMock()
    mock_telemetry.track_operation.return_value.__enter__ = MagicMock()
    mock_telemetry.track_operation.return_value.__exit__ = MagicMock(return_value=False)

    # Mock DatabaseManager to avoid requiring PostgreSQL connection
    mock_db = MagicMock()

    session = NoHeadSession()

    # Patch DatabaseManager during service initialization
    with patch("src.services.url_verification.DatabaseManager", return_value=mock_db):
        svc = URLVerificationService(
            http_session=session,
            run_http_precheck=False,
            telemetry_tracker=mock_telemetry,
        )

    dummy = DummySniffer()
    svc.sniffer = dummy

    res = svc.verify_url("https://example.com/article")
    assert res["storysniffer_result"] is True
    assert dummy.called
