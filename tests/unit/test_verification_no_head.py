from src.services.url_verification import URLVerificationService


class NoHeadSession:
    def __init__(self):
        self.headers = {}

    def head(self, *a, **kw):
        raise RuntimeError('HEAD should not be called')


class DummySniffer:
    def __init__(self):
        self.called = False

    def guess(self, url):
        self.called = True
        return True


def test_verification_uses_storysniffer_and_no_head(monkeypatch):
    session = NoHeadSession()
    svc = URLVerificationService(http_session=session)

    dummy = DummySniffer()
    svc.sniffer = dummy

    res = svc.verify_url('https://example.com/article')
    assert res['storysniffer_result'] is True
    assert dummy.called
