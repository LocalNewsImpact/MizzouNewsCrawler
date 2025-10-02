from src.utils import url_utils


def test_normalize_url_removes_query_and_fragment():
    url = "https://example.com/story?id=123#section"
    assert url_utils.normalize_url(url) == "https://example.com/story"


def test_normalize_url_preserves_trailing_slash_for_root():
    url = "https://example.com/"
    assert url_utils.normalize_url(url) == "https://example.com/"


def test_normalize_url_removes_trailing_slash_from_path():
    url = "https://example.com/news/"
    assert url_utils.normalize_url(url) == "https://example.com/news"


def test_normalize_url_handles_invalid_input():
    class Odd:
        def __str__(self):
            raise ValueError("boom")

    original = "not-a-url"
    assert url_utils.normalize_url(original) == original


def test_normalize_url_returns_original_for_blank_input():
    assert url_utils.normalize_url("   ") == "   "


def test_is_same_article_url_uses_normalization():
    assert url_utils.is_same_article_url(
        "https://example.com/story", "https://example.com/story?ref=home"
    )


def test_is_same_article_url_rejects_missing_values():
    assert not url_utils.is_same_article_url("", "https://example.com")
    assert not url_utils.is_same_article_url("https://example.com", "")


def test_extract_base_url_returns_none_for_invalid():
    assert url_utils.extract_base_url("") is None
    assert url_utils.extract_base_url("nota url") == "://"


def test_extract_base_url_parses_valid_url():
    assert (
        url_utils.extract_base_url("https://sub.example.com/path")
        == "https://sub.example.com"
    )


def test_normalize_url_logs_when_parsing_fails(monkeypatch, caplog):
    def boom(url):
        raise ValueError("fail")

    monkeypatch.setattr(url_utils, "urlparse", boom)

    with caplog.at_level("WARNING"):
        result = url_utils.normalize_url("https://problem")

    assert result == "https://problem"
    assert "Failed to normalize" in caplog.text
