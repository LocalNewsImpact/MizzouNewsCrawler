"""One page, one candidate_link -- regardless of scheme or www.

upsert_candidate_link deduplicates on a scheme- and www-agnostic path, but the
lookup rebuilt candidate URLs from that stripped path while storage kept "www.".
So it searched for "https://example.com/x" against a row stored as
"https://www.example.com/x", never matched, and inserted a second row for the
other scheme.

Effect in production: one publisher held 471 candidate_links against 300
articles. 142 links were marked 'extracted' with no article of their own --
their article existed under the other scheme's link. Not data loss, but a link
asserting an article it did not have, which is indistinguishable from loss when
querying by candidate_link_id.

https wins: both schemes serve the same page, and converging on the secure form
stops later discoveries alternating and re-creating the split.
"""

import pytest

from src.models.database import upsert_candidate_link


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.filtered = None

    def filter(self, criterion):
        self.criterion = criterion
        return self

    def order_by(self, *_):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class _Session:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.added = []
        self.committed = 0
        self.last_query = None

    def query(self, _model):
        self.last_query = _Query(self.rows)
        return self.last_query

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed += 1


class _Existing:
    def __init__(self, url):
        self.url = url
        self.source = "seed"


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    monkeypatch.setattr(
        "src.models.database._commit_with_retry", lambda session: session.commit()
    )


def _candidates(session):
    """The URL forms the dedup lookup actually searched for."""
    return list(session.last_query.criterion.right.value)


class TestLookupCoversStoredForms:
    def test_www_variants_are_searched(self):
        """The regression: storage keeps www., so the lookup must too."""
        session = _Session()
        upsert_candidate_link(session, "https://www.example.com/story", source="s")
        assert "https://www.example.com/story" in _candidates(session)

    def test_both_schemes_are_searched(self):
        session = _Session()
        upsert_candidate_link(session, "https://www.example.com/story", source="s")
        found = _candidates(session)
        assert "http://www.example.com/story" in found
        assert "https://www.example.com/story" in found

    def test_bare_host_variants_are_searched_too(self):
        session = _Session()
        upsert_candidate_link(session, "https://www.example.com/story", source="s")
        found = _candidates(session)
        assert "https://example.com/story" in found
        assert "http://example.com/story" in found


class TestNoSecondRowPerScheme:
    def test_http_row_is_reused_for_the_https_discovery(self):
        """The exact production shape: http seen first, https seen later."""
        session = _Session(rows=[_Existing("http://www.example.com/story")])
        upsert_candidate_link(session, "https://www.example.com/story", source="s")
        assert session.added == [], "a second row per scheme is the bug"

    def test_the_surviving_row_is_upgraded_to_https(self):
        session = _Session(rows=[_Existing("http://www.example.com/story")])
        link = upsert_candidate_link(
            session, "https://www.example.com/story", source="s"
        )
        assert link.url == "https://www.example.com/story"

    def test_https_is_not_downgraded_by_a_later_http_sighting(self):
        session = _Session(rows=[_Existing("https://www.example.com/story")])
        link = upsert_candidate_link(
            session, "http://www.example.com/story", source="s"
        )
        assert link.url == "https://www.example.com/story"

    def test_a_genuinely_new_url_still_inserts(self):
        session = _Session()
        upsert_candidate_link(session, "https://www.example.com/fresh", source="s")
        assert len(session.added) == 1
