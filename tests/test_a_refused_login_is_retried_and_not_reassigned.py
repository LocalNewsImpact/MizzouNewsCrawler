"""A refused login is not handed out again, and is retried on a new driver.

Measured on the seven-host WSU rotation, 2026-09-21. union-bulletin and
pendoreillerivervalley both failed to log in at 03:47 UTC and were correctly
refused -- nothing fetched, no wall stored. Then two things went wrong at once.

THE QUEUE KEPT OFFERING THEM. `/stats` reported both as unclaimable ("login
failed on a recent run -- needs re-validation") while `_get_available_domains`
never read `auth_last_failed_at`. They were assigned 13 and 11 more times: a
quarter of the night's turns, each followed by the batch sleep. The report and the
selector disagreed, which is why the stats looked right while the worker wasted
the night. Now one clause, `LOGIN_COOLING_DOWN`, is used by both.

THE REFUSAL NEVER ENDED. `_auth_failed_domains` and the login budget are reset
when the driver is rebuilt -- a new driver is a new chance -- but every refused
article also counted in `_selenium_failure_counts`, which is checked BEFORE the
login and never reset. It passed 3 on the first turn, and "Skipping Selenium ...
already failed 8 times" kept union-bulletin from being logged into again across
13 driver rebuilds. A transient failure -- its login page timed out -- became a
refusal for the rest of the run.

The window is a trade, stated so it is chosen rather than inherited: 2 login
attempts per driver after each `AUTH_FAILURE_COOLDOWN_SECONDS`, instead of 2
attempts and then never. A publisher with a lockout counter wants a longer window.
"""

from __future__ import annotations

import inspect
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.services import work_queue as wq


@pytest.fixture
def coordinator():
    return wq.WorkQueueCoordinator(db=MagicMock())


class TestTheClause:
    @pytest.fixture
    def sources(self):
        """The clause run for real, on SQLite -- the dialect the interval literal
        this replaced could not parse. Postgres was checked on production rows
        on 2026-09-21."""
        from datetime import datetime, timedelta

        from sqlalchemy import create_engine, text

        engine = create_engine("sqlite://")
        now = datetime.utcnow()
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TABLE sources (host TEXT, auth_last_failed_at TIMESTAMP)")
            )
            conn.execute(
                text("INSERT INTO sources VALUES (:h, :t)"),
                [
                    {"h": "never-failed", "t": None},
                    {"h": "failed-just-now", "t": now - timedelta(minutes=5)},
                    {"h": "failed-last-night", "t": now - timedelta(hours=6)},
                ],
            )
        return engine

    def _offered(self, engine) -> set[str]:
        from sqlalchemy import text

        with engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT host FROM sources s WHERE NOT {wq.LOGIN_COOLING_DOWN}"),
                {"login_cooldown_cutoff": wq.login_cooldown_cutoff()},
            )
            return {r[0] for r in rows}

    def test_a_recent_failure_is_withheld(self, sources):
        assert "failed-just-now" not in self._offered(sources)

    def test_it_recovers_without_a_person(self, sources):
        """Last night's union-bulletin failure is offered again this morning."""
        assert "failed-last-night" in self._offered(sources)

    def test_a_host_that_never_failed_is_offered(self, sources):
        """`IS NOT NULL` first: a NULL comparison is NULL, and NOT NULL is NULL,
        which a WHERE treats as false -- every healthy host would vanish."""
        assert "never-failed" in self._offered(sources)

    def test_the_cutoff_is_naive_utc(self):
        """The column is `timestamp without time zone`, written by `NOW()` in a
        UTC session. An aware value would not compare on SQLite."""
        from datetime import datetime

        cutoff = wq.login_cooldown_cutoff()
        assert cutoff.tzinfo is None
        expected = datetime.utcnow().timestamp() - wq.AUTH_FAILURE_COOLDOWN_SECONDS
        assert abs(cutoff.timestamp() - expected) < 5

    def test_the_default_is_two_hours(self, monkeypatch):
        import importlib

        monkeypatch.delenv("AUTH_FAILURE_COOLDOWN_SECONDS", raising=False)
        assert importlib.reload(wq).AUTH_FAILURE_COOLDOWN_SECONDS == 7200

    def test_the_window_is_overridable(self, monkeypatch):
        """A publisher with a lockout counter wants a longer window."""
        import importlib

        monkeypatch.setenv("AUTH_FAILURE_COOLDOWN_SECONDS", "86400")
        try:
            assert importlib.reload(wq).AUTH_FAILURE_COOLDOWN_SECONDS == 86400
        finally:
            monkeypatch.delenv("AUTH_FAILURE_COOLDOWN_SECONDS")
            importlib.reload(wq)


class TestTheSelectorAndTheReportAgree:
    @pytest.mark.parametrize("requires_login", [True, False, None])
    def test_every_pool_excludes_a_cooling_host(self, coordinator, requires_login):
        """A `mixed` worker draws credentialed hosts too, so this is not only the
        authenticated pool's rule."""
        session = MagicMock()
        session.execute.return_value = iter([])
        coordinator._get_available_domains(session, None, requires_login=requires_login)
        sql, params = session.execute.call_args.args
        assert f"NOT {wq.LOGIN_COOLING_DOWN}" in str(sql)
        assert isinstance(params["login_cooldown_cutoff"], datetime)

    def test_the_report_uses_the_same_clause(self):
        """The disagreement was the bug. Asserted on the source of get_stats so a
        second, drifting definition cannot creep back in."""
        source = inspect.getsource(wq.WorkQueueCoordinator.get_stats)
        assert "LOGIN_COOLING_DOWN" in source
        assert "s.auth_last_failed_at IS NOT NULL AS needs_revalidation" not in source

    def test_the_report_says_when_it_comes_back(self):
        source = inspect.getsource(wq.WorkQueueCoordinator.get_stats)
        assert "not offered for" in source
        assert "validate-login --record" in source

    def test_the_clause_is_not_a_bare_literal_in_the_stats_sql(self, coordinator):
        """The stats query is triple-quoted; a `" + X + "` edit inside it becomes
        literal SQL text. That happened while writing this fix."""
        seen = []

        def capture(query, params=None, *a, **k):
            seen.append((str(query), params or {}))
            result = MagicMock()
            result.fetchall.return_value = []
            result.fetchone.return_value = (0,)
            result.scalar.return_value = 0
            return result

        coordinator._test_session = MagicMock()
        coordinator._test_session.execute.side_effect = capture
        try:
            coordinator.get_stats()
        except Exception:
            pass
        credentialed = [(q, p) for q, p in seen if "needs_revalidation" in q]
        assert credentialed, "the credentialed stats query never ran"
        sql, params = credentialed[0]
        assert wq.LOGIN_COOLING_DOWN in sql
        assert '" + ' not in sql
        assert "login_cooldown_cutoff" in params


class TestARefusalIsNotABrowserFailure:
    def _source(self, name: str) -> str:
        from src.crawler import ContentExtractor

        src = inspect.getsource(getattr(ContentExtractor, name))
        return "\n".join(
            line for line in src.splitlines() if not line.strip().startswith("#")
        )

    def _method_containing(self, needle: str) -> str:
        from src.crawler import ContentExtractor

        for name, member in inspect.getmembers(ContentExtractor):
            if callable(member):
                try:
                    src = inspect.getsource(member)
                except (OSError, TypeError):
                    continue
                if needle in src:
                    return name
        raise AssertionError(f"no method contains {needle!r}")

    def test_the_empty_result_increment_skips_refused_hosts(self):
        name = self._method_containing("Selenium returned empty result")
        body = self._source(name)
        guard = body.index("not in ContentExtractor._auth_failed_domains")
        increment = body.index("self._selenium_failure_counts[dom] = (")
        assert guard < increment

    def test_the_guard_compares_bare_hosts(self):
        """`dom` is the netloc (www.union-bulletin.com); `_auth_failed_domains`
        holds the bare host (union-bulletin.com). Comparing them raw would never
        match and the fix would do nothing."""
        name = self._method_containing("Selenium returned empty result")
        body = self._source(name)
        assert (
            "self._bare_host(dom) not in ContentExtractor._auth_failed_domains" in body
        )

    def test_the_login_caches_are_still_reset_on_a_new_driver(self):
        """The half that already worked, pinned so the retry keeps working."""
        from src.crawler import ContentExtractor

        src = inspect.getsource(ContentExtractor)
        assert "ContentExtractor._auth_failed_domains = set()" in src
        assert "ContentExtractor._auth_attempts = {}" in src


class TestASuccessfulLoginClearsTheFlag:
    def test_success_records_it(self):
        from src.crawler import ContentExtractor

        body = inspect.getsource(ContentExtractor._ensure_authenticated)
        established = body.index('"Authenticated session established for %s"')
        assert "self._record_login_success(host)" in body[established:]

    def test_it_touches_only_rows_that_carry_a_failure(self):
        """The ordinary login, which never failed, writes nothing."""
        from src.crawler import ContentExtractor

        src = inspect.getsource(ContentExtractor._record_login_success)
        assert "auth_last_failed_at IS NOT NULL" in src
        assert "auth_last_failed_at = NULL" in src

    def test_a_database_error_does_not_break_a_working_login(self):
        from src.crawler import ContentExtractor

        extractor = ContentExtractor.__new__(ContentExtractor)
        with patch(
            "src.models.database.DatabaseManager", side_effect=RuntimeError("db gone")
        ):
            extractor._record_login_success("union-bulletin.com")  # must not raise
