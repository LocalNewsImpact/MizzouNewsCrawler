import types
import pytest


class DummySession:
    def __init__(self):
        self.headers = {}

    def head(self, *args, **kwargs):
        raise RuntimeError('HEAD should not be called in verification')


class DummySniffer:
    def __init__(self):
        self.called = False

    def guess(self, url):
        self.called = True
        return True


def test_verify_url_uses_storysniffer_and_no_head(monkeypatch):
    from src.services.url_verification import URLVerificationService

    dummy_session = DummySession()
    svc = URLVerificationService(http_session=dummy_session)

    # Patch the internal sniffer to a dummy that records calls
    dummy_sniffer = DummySniffer()
    svc.sniffer = dummy_sniffer

    # Call verify_url - should not raise from DummySession.head
    result = svc.verify_url('https://example.com/some-article')
    assert result['storysniffer_result'] is True
    assert dummy_sniffer.called
