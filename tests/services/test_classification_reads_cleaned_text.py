"""The classifier sees headline PLUS cleaned body, falling back to the raw one.

Two things are pinned here.

Title is combined with the body rather than used as a last resort: a headline
is a dense statement of what a story is about, which is the judgement the CIN
classifier makes.

The body is the CLEANED column. Reading `content` first meant classifying
whatever the page carried — navigation menus, paywall prompts, cookie notices.
For the 3% of stored articles that are mostly nav chrome, the label came from a
list of section names rather than from any reporting. That order was harmless
while extraction wrote the same string to both columns and became wrong the
moment they diverged.
"""

from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from src.services.classification_service import ArticleClassificationService

NAV = "Skip to main content Home Categories Classifieds Columns Government"
BODY = "The county commission voted 4-1 on Tuesday to approve the measure."
HEAD = "Commission approves measure"


class _Article:
    def __init__(self, content=None, text=None, title=None):
        self.content = content
        self.text = text
        self.title = title


def _service() -> ArticleClassificationService:
    session = MagicMock(spec=Session)
    session.bind = None
    session.scalars = MagicMock(return_value=iter(()))
    return ArticleClassificationService(session=session)


class TestTitleAndBodyTogether:
    def test_headline_and_body_are_both_classified(self):
        out = _service()._prepare_text(_Article(text=BODY, title=HEAD))
        assert HEAD in out
        assert BODY in out

    def test_headline_comes_first(self):
        out = _service()._prepare_text(_Article(text=BODY, title=HEAD))
        assert out.index(HEAD) < out.index(BODY)

    def test_body_alone_when_untitled(self):
        assert _service()._prepare_text(_Article(text=BODY)) == BODY

    def test_headline_alone_when_there_is_no_body(self):
        assert _service()._prepare_text(_Article(title=HEAD)) == HEAD


class TestBodyPrefersCleaned:
    def test_cleaned_body_wins_over_raw_capture(self):
        out = _service()._prepare_text(_Article(content=NAV, text=BODY, title=HEAD))
        assert BODY in out
        assert "Classifieds" not in out

    def test_raw_is_used_when_there_is_no_cleaned_body(self):
        """Rows extracted before the raw/cleaned split have only `content`."""
        out = _service()._prepare_text(_Article(content=BODY, title=HEAD))
        assert BODY in out

    def test_blank_cleaned_body_falls_back_to_raw(self):
        out = _service()._prepare_text(_Article(content=BODY, text="  \n "))
        assert BODY in out

    def test_only_one_body_is_used_never_both(self):
        out = _service()._prepare_text(_Article(content=NAV, text=BODY))
        assert out == BODY

    def test_nothing_to_classify_returns_none(self):
        assert _service()._prepare_text(_Article("", "  ", " ")) is None

    def test_body_preference_is_explicit(self):
        """Pinned so a later tidy-up cannot silently reorder it."""
        assert ArticleClassificationService._BODY_FIELD_PREFERENCE == (
            "text",
            "content",
        )
