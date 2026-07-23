import types

import pytest


class DummySession:
    def __init__(self):
        self.headers = {}

    def head(self, *args, **kwargs):
        raise RuntimeError("HEAD should not be called in verification")


class DummySniffer:
    def __init__(self):
        self.called = False

    def guess(self, url):
        self.called = True
        return True


def test_verify_url_uses_storysniffer_and_no_head(monkeypatch):
    from src.services.url_verification import URLVerificationService

    dummy_session = DummySession()
    svc = URLVerificationService(http_session=dummy_session, run_http_precheck=False)

    # Patch the internal sniffer to a dummy that records calls
    dummy_sniffer = DummySniffer()
    svc.sniffer = dummy_sniffer

    # Call verify_url - should not raise from DummySession.head
    result = svc.verify_url("https://example.com/some-article")
    assert result["storysniffer_result"] is True
    assert dummy_sniffer.called


def _svc_with_sniffer():
    """A service whose sniffer would say YES to anything — the favicon bug.

    StorySniffer.guess() returns truthy for WordPress favicons, so a passing
    sniffer is exactly the condition under which the extension gate must fire
    FIRST and keep asset URLs out of the article queue.
    """
    from src.services.url_verification import URLVerificationService

    svc = URLVerificationService(http_session=DummySession(), run_http_precheck=False)
    svc.sniffer = DummySniffer()
    return svc


class TestAssetExtensionsRejectedBeforeStorySniffer:
    """Image/asset URLs must be filtered before the sniffer or an HTTP fetch.

    The extension filter used to live in check_is_article(), now dead code. In
    one production run 15 favicon URLs across 11 papers were marked 'article'
    and each wasted an extraction fetch.
    """

    FAVICON = (
        "https://www.memphisdemocrat.com/wp-content/uploads/2021/03/favicon-16x16-1.png"
    )

    def test_favicon_is_not_an_article(self):
        svc = _svc_with_sniffer()
        result = svc.verify_url(self.FAVICON)
        assert result["pattern_status"] == "not_article"
        assert result["pattern_type"] == "asset_extension"

    def test_sniffer_is_never_consulted_for_an_asset(self):
        svc = _svc_with_sniffer()
        svc.verify_url(self.FAVICON)
        assert svc.sniffer.called is False

    def test_various_asset_extensions_are_rejected(self):
        svc = _svc_with_sniffer()
        for url in (
            "https://ex.com/a/logo.jpg",
            "https://ex.com/x.jpeg",
            "https://ex.com/y.gif",
            "https://ex.com/z.svg",
            "https://ex.com/doc.pdf",
            "https://ex.com/style.css",
        ):
            assert svc.verify_url(url)["pattern_status"] == "not_article", url

    def test_query_string_after_extension_still_rejected(self):
        svc = _svc_with_sniffer()
        result = svc.verify_url("https://ex.com/img/favicon.png?v=2")
        assert result["pattern_status"] == "not_article"

    def test_article_slug_containing_png_is_not_an_asset(self):
        """`.png` in the middle of a slug must not trigger the gate — the check
        is on the path's final segment, not a substring."""
        svc = _svc_with_sniffer()
        result = svc.verify_url("https://ex.com/news/new-png-format-explained/")
        # Falls through to the sniffer (which says yes here), NOT the asset gate.
        assert result["pattern_type"] != "asset_extension"
        assert svc.sniffer.called is True
