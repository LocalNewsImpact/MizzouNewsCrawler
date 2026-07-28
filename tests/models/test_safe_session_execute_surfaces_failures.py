"""safe_session_execute retries only what is retryable.

It caught bare Exception and `pass`ed, falling through to the string-based
handler for ANY failure of a SQLAlchemy Core statement. The fallback re-executes,
so a genuine error did still surface -- but only after running the statement a
second time, which for a non-idempotent write is a second attempt nobody asked
for, against a connection whose transaction the first failure may already have
aborted.

Scope note, because the temptation is to claim more: this was investigated while
chasing 176 candidate_links marked 'extracted' with no article row (142 with no
article anywhere). This swallow is NOT established as the cause -- the fallback
re-raises, so the caller was not silently told the write succeeded. It is fixed
here as a real defect on its own terms; the orphaned rows still need their own
root cause, and the caller-side rowcount guard is what protects against them.

Only ArgumentError may fall through -- that is the signal for the legacy
parameter styles the fallback exists to retry.
"""

import pytest
from sqlalchemy.exc import ArgumentError
from sqlalchemy.sql import text

from src.models.database import safe_session_execute


class _Session:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    def execute(self, sql, params=None):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return "executed"


class TestFailuresSurface:
    def test_database_error_propagates(self):
        """A failing statement must reach the caller (true before and after)."""
        boom = RuntimeError("duplicate key violates uq_articles_url")
        session = _Session(error=boom)
        with pytest.raises(RuntimeError, match="uq_articles_url"):
            safe_session_execute(session, text("INSERT INTO articles ..."), {"id": 1})

    def test_it_does_not_silently_retry_a_real_failure(self):
        """THE regression: a non-retryable failure must not be re-executed.

        This is the assertion that fails on the previous implementation.
        """
        session = _Session(error=RuntimeError("nope"))
        with pytest.raises(RuntimeError):
            safe_session_execute(session, text("INSERT INTO x ..."), {"id": 1})
        assert session.calls == 1, "a non-ArgumentError must not be retried"

    def test_argument_error_still_falls_through(self):
        """The fallback's actual purpose is preserved."""
        session = _Session(error=ArgumentError("legacy param style"))
        # Falls through to string handling; that path re-executes and this stub
        # raises again, so the ArgumentError is what escapes -- the point is that
        # it was ATTEMPTED a second time rather than surfacing immediately.
        with pytest.raises(ArgumentError):
            safe_session_execute(session, text("SELECT 1"), {"a": 1})
        assert session.calls == 2, "ArgumentError must trigger the retry"

    def test_success_returns_the_result(self):
        session = _Session()
        assert safe_session_execute(session, text("SELECT 1"), {"a": 1}) == "executed"
