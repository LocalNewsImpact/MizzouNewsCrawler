import sys
import types

import pytest
from click.testing import CliRunner

from src.cli.commands import content_cleaning as content_cleaning_cmd
from src.cli.commands import discovery as discovery_cmd
from src.cli.commands import telemetry as telemetry_cmd


class FakeTelemetry:
    def __init__(
        self,
        *,
        errors=None,
        methods=None,
        publishers=None,
        fields=None,
        field_stats=None,
    ):
        self._errors = errors or []
        self._methods = methods or []
        self._publishers = publishers or []
        self._fields = fields or []
        self._field_stats = field_stats or []

    # Telemetry helpers expected by CLI commands
    def get_error_summary(self, days):
        return self._errors

    def get_method_effectiveness(self, publisher=None):
        return self._methods

    def get_publisher_stats(self):
        return self._publishers

    def get_field_extraction(self, publisher=None, method=None):
        return self._fields

    def get_field_extraction_stats(self, publisher=None, method=None):
        return self._field_stats


def _install_sqlite_stub(monkeypatch, *, fetchall=None, fetchone=None):
    class StubCursor:
        def __init__(self):
            self._fetchall = list(fetchall or [])
            self._fetchone = fetchone

        def execute(self, *args, **kwargs):
            return self

        def fetchall(self):
            return list(self._fetchall)

        def fetchone(self):
            return self._fetchone

        def close(self):
            pass

    class StubConnection:
        def __init__(self):
            self._cursor = StubCursor()

        def cursor(self):
            return self._cursor

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(
        content_cleaning_cmd.sqlite3,
        "connect",
        lambda *a, **k: StubConnection(),
    )


@pytest.fixture
def fake_sqlite(monkeypatch):
    """Provide a deterministic sqlite3.connect stub for CLI tests."""

    class FakeCursor:
        def __init__(self):
            self._data = []

        def execute(self, query, params=None):
            domain_rows = [
                (
                    "https://example.com/article-a",
                    "uuid-1",
                    "Original article content",
                    len("Original article content"),
                ),
                (
                    "https://example.com/article-b",
                    "uuid-2",
                    "Different content body",
                    len("Different content body"),
                ),
            ]
            self._data = domain_rows
            return self

        def fetchall(self):
            return list(self._data)

        def close(self):
            pass

    class FakeConnection:
        def __init__(self):
            self._cursor = FakeCursor()

        def cursor(self):
            return self._cursor

        def close(self):
            pass

    def connect_stub(_path):
        return FakeConnection()

    monkeypatch.setattr(content_cleaning_cmd.sqlite3, "connect", connect_stub)
    return connect_stub


@pytest.fixture
def fake_cleaner(monkeypatch):
    """Replace ImprovedContentCleaner with a lightweight stub."""

    class StubTelemetry:
        def __init__(self, content):
            self.processing_time = 0.05
            self.original_length = len(content)
            self.cleaned_length = max(len(content) - 5, 0)
            self.segments_removed = 1
            self.removed_segments = [
                {
                    "pattern_type": "footer",
                    "confidence": 0.92,
                    "text": "unsubscribe",
                }
            ]

    class StubCleaner:
        def __init__(self, *args, **kwargs):
            self.calls = []

        def clean_content(self, content, domain, article_id, dry_run):
            self.calls.append((domain, article_id))
            telemetry = StubTelemetry(content)
            return content.rstrip(), telemetry

    cleaner = StubCleaner()
    monkeypatch.setattr(
        content_cleaning_cmd, "ImprovedContentCleaner", lambda *a, **k: cleaner
    )
    return cleaner


def test_handle_discovery_command_invokes_pipeline(monkeypatch, capsys):
    captured = {}

    class FakeDiscovery:
        def __init__(self, max_articles_per_source, days_back):
            captured["init"] = {
                "max_articles_per_source": max_articles_per_source,
                "days_back": days_back,
            }
            self.telemetry = types.SimpleNamespace(
                list_active_operations=lambda: [],
                get_failure_summary=lambda *_a, **_k: {"total_failures": 0},
            )

        def run_discovery(self, **kwargs):
            captured["run"] = kwargs
            return {
                "sources_available": 5,
                "sources_due": 3,
                "sources_skipped": 1,
                "sources_processed": 2,
                "sources_succeeded": 2,
                "sources_failed": 0,
                "sources_with_content": 2,
                "sources_no_content": 0,
                "total_candidates_discovered": 8,
            }

    import src.crawler.discovery as discovery_module

    monkeypatch.setattr(discovery_module, "NewsDiscovery", FakeDiscovery)

    args = types.SimpleNamespace(
        source_uuid="uuid-one",
        source_uuids=["uuid-two"],
        legacy_article_limit=20,
        max_articles=99,
        days_back=3,
        dataset="daily",
        source_limit=4,
        source_filter="gazette",
        due_only=True,
        force_all=False,
        host="example.com",
        city="Columbia",
        county="Boone",
        host_limit=2,
        existing_article_limit=None,
    )

    exit_code = discovery_cmd.handle_discovery_command(args)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Sources processed: 2" in out
    assert captured["init"]["max_articles_per_source"] == 20
    assert captured["run"]["due_only"] is True
    assert captured["run"]["source_uuids"] == ["uuid-one", "uuid-two"]


def test_content_cleaning_analyze_domains_cli(fake_sqlite, fake_cleaner):
    runner = CliRunner()

    result = runner.invoke(
        content_cleaning_cmd.content_cleaning,
        [
            "analyze-domains",
            "--min-articles",
            "1",
            "--confidence-threshold",
            "0.5",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    output = result.output
    assert "Analyzing" in output
    assert "📊 Domain" in output
    assert fake_cleaner.calls, "Cleaner should have been invoked"


def test_handle_telemetry_errors_command(monkeypatch, capsys):
    sample_errors = [
        {
            "error_type": "timeout",
            "host": "example.com",
            "status_code": 504,
            "count": 4,
            "last_seen": "2025-09-25T12:00:00Z",
        }
    ]

    monkeypatch.setattr(
        telemetry_cmd,
        "ComprehensiveExtractionTelemetry",
        lambda: FakeTelemetry(errors=sample_errors),
    )

    args = types.SimpleNamespace(telemetry_command="errors", days=3)
    exit_code = telemetry_cmd.handle_telemetry_command(args)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "HTTP Error Summary" in out
    assert "example.com" in out


def test_handle_telemetry_missing_subcommand(monkeypatch, capsys):
    monkeypatch.setattr(
        telemetry_cmd,
        "ComprehensiveExtractionTelemetry",
        lambda: FakeTelemetry(),
    )

    args = types.SimpleNamespace(telemetry_command=None)
    exit_code = telemetry_cmd.handle_telemetry_command(args)
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "please specify" in out.lower()


def test_handle_telemetry_methods_command(monkeypatch, capsys):
    sample_methods = [
        {
            "successful_method": "newspaper4k",
            "count": 10,
            "success_rate": 0.75,
            "avg_duration": 1200,
        }
    ]

    monkeypatch.setattr(
        telemetry_cmd,
        "ComprehensiveExtractionTelemetry",
        lambda: FakeTelemetry(methods=sample_methods),
    )

    args = types.SimpleNamespace(telemetry_command="methods", publisher=None)
    exit_code = telemetry_cmd.handle_telemetry_command(args)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Extraction Method Effectiveness" in out
    assert "newspaper4k" in out
    assert "75.0" in out


def test_handle_telemetry_publishers_command(monkeypatch, capsys):
    sample_publishers = [
        {
            "publisher": "Example News",
            "host": "example.com",
            "total_attempts": 5,
            "successful": 3,
            "avg_duration_ms": 1500,
        },
        {
            "publisher": "Example News",
            "host": "news.example.com",
            "total_attempts": 2,
            "successful": 2,
            "avg_duration_ms": 1000,
        },
    ]

    monkeypatch.setattr(
        telemetry_cmd,
        "ComprehensiveExtractionTelemetry",
        lambda: FakeTelemetry(publishers=sample_publishers),
    )

    args = types.SimpleNamespace(telemetry_command="publishers")
    exit_code = telemetry_cmd.handle_telemetry_command(args)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Publisher Performance Statistics" in out
    assert "Example News" in out
    assert "Overall" in out


def test_handle_telemetry_fields_command(monkeypatch, capsys):
    field_stats = [
        {
            "method": "newspaper4k",
            "title_success_rate": 0.9,
            "author_success_rate": 0.5,
            "content_success_rate": 0.8,
            "date_success_rate": 0.7,
            "count": 4,
        },
        {
            "method": "selenium",
            "title_success_rate": 0.6,
            "author_success_rate": 0.3,
            "content_success_rate": 0.5,
            "date_success_rate": 0.4,
            "count": 2,
        },
    ]

    monkeypatch.setattr(
        telemetry_cmd,
        "ComprehensiveExtractionTelemetry",
        lambda: FakeTelemetry(field_stats=field_stats),
    )

    args = types.SimpleNamespace(
        telemetry_command="fields",
        publisher=None,
        method=None,
    )
    exit_code = telemetry_cmd.handle_telemetry_command(args)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Field Extraction Analysis" in out
    assert "newspaper4k" in out
    assert "Total Records" in out


def test_handle_telemetry_command_logs_exception(monkeypatch):
    class Boom(Exception):
        pass

    monkeypatch.setattr(
        telemetry_cmd,
        "ComprehensiveExtractionTelemetry",
        lambda: (_ for _ in ()).throw(Boom("nope")),
    )

    args = types.SimpleNamespace(telemetry_command="methods", publisher=None)
    exit_code = telemetry_cmd.handle_telemetry_command(args)

    assert exit_code == 1


def test_apply_cleaning_reports_when_no_articles(monkeypatch):
    _install_sqlite_stub(monkeypatch, fetchall=[])

    runner = CliRunner()
    result = runner.invoke(
        content_cleaning_cmd.content_cleaning,
        ["apply-cleaning", "--dry-run"],
    )

    assert result.exit_code == 0
    assert "No articles found" in result.output


def test_clean_article_handles_missing_record(monkeypatch):
    _install_sqlite_stub(monkeypatch, fetchone=None)

    runner = CliRunner()
    result = runner.invoke(
        content_cleaning_cmd.content_cleaning,
        ["clean-article", "missing-id"],
    )

    assert result.exit_code == 0
    assert "Article not found" in result.output


@pytest.mark.skip(
    reason="src.cli.main is deprecated, test needs update for cli_modular"
)
def test_main_dispatch_invokes_load_sources(monkeypatch):
    from src.cli import main as main_module

    captured = {}

    def fake_setup(level):
        captured["log_level"] = level

    def fake_load(args):
        captured["csv"] = args.csv
        return 7

    monkeypatch.setattr(main_module, "setup_logging", fake_setup)
    monkeypatch.setattr(main_module, "load_sources_command", fake_load)
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--log-level", "DEBUG", "load-sources", "--csv", "foo.csv"],
    )

    exit_code = main_module.main()

    assert exit_code == 7
    assert captured["log_level"] == "DEBUG"
    assert captured["csv"] == "foo.csv"


def test_main_dispatch_handles_missing_command(monkeypatch, capsys):
    from src.cli import main as main_module

    monkeypatch.setattr(sys, "argv", ["prog"])

    exit_code = main_module.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "usage" in captured.out.lower()


def test_main_dispatch_invokes_discover_urls(monkeypatch):
    from src.cli import main as main_module

    captured = {}

    def fake_discover(args):
        captured["force_all"] = args.force_all
        captured["source_limit"] = args.source_limit
        return 0

    monkeypatch.setattr(main_module, "setup_logging", lambda *_: None)
    monkeypatch.setattr(main_module, "discover_urls_command", fake_discover)
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "discover-urls", "--source-limit", "3", "--force-all"],
    )

    exit_code = main_module.main()

    assert exit_code == 0
    assert captured["force_all"] is True
    assert captured["source_limit"] == 3


def test_apply_cleaning_updates_articles(monkeypatch, fake_cleaner):
    rows = [
        ("article-1", "https://example.com/a", "Content one   "),
        ("article-2", "https://example.com/b", "Another body   "),
    ]

    class StubCursor:
        def __init__(self, items):
            self._items = list(items)
            self.executed = []
            self.executemany_calls = []

        def execute(self, query, params=None):
            self.executed.append((query, list(params or [])))
            return self

        def executemany(self, query, param_seq):
            self.executemany_calls.append((query, list(param_seq)))

        def fetchall(self):
            return list(self._items)

        def fetchone(self):
            return None

        def close(self):
            pass

    class StubConnection:
        def __init__(self, items):
            self.cursor_obj = StubCursor(items)
            self.commits = 0

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            self.commits += 1

        def close(self):
            pass

    stub_conn = StubConnection(rows)

    monkeypatch.setattr(
        content_cleaning_cmd.sqlite3,
        "connect",
        lambda _path: stub_conn,
    )

    runner = CliRunner()
    result = runner.invoke(
        content_cleaning_cmd.content_cleaning,
        ["apply-cleaning", "--limit", "2", "--verbose"],
    )

    assert result.exit_code == 0
    assert "Updated 2 articles" in result.output
    assert stub_conn.commits == 1
    assert stub_conn.cursor_obj.executemany_calls

    update_query, update_params = stub_conn.cursor_obj.executemany_calls[0]
    assert "UPDATE articles" in update_query
    assert update_params == [(row[2].rstrip(), row[0]) for row in rows]
