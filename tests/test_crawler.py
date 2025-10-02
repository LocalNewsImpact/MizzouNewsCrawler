import sys
from pathlib import Path

# Ensure project root is on sys.path so tests can import `src` as a
# top-level package
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.crawler import NewsCrawler  # noqa: E402


def test_is_valid_url():
    nc = NewsCrawler()
    assert nc.is_valid_url("https://example.com")
    assert nc.is_valid_url("http://sub.domain.example/path")
    assert not nc.is_valid_url("not-a-url")
    # ftp scheme should be treated as invalid for our crawler
    assert not nc.is_valid_url("ftp://example.com")


def test_is_likely_article():
    nc = NewsCrawler()
    # A typical article URL
    assert nc._is_likely_article("https://example.com/2023/09/15/some-article")
    # Skip pattern
    assert not nc._is_likely_article("https://example.com/page/2")

    # Site rules include/exclude pattern examples
    rules = {
        "include_patterns": ["/news/"],
        "exclude_patterns": ["/weather/"],
    }
    assert nc._is_likely_article("https://example.com/news/interesting", rules)
    assert not nc._is_likely_article("https://example.com/weather/today", rules)
