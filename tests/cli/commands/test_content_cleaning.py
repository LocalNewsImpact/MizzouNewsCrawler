import click
import pytest
from click.testing import CliRunner

from src.cli.commands import content_cleaning as cc


@pytest.fixture
def runner():
    return CliRunner()


def _install_sqlite_stub(monkeypatch, rows, *, fetchone=None):
    class CursorStub:
        def __init__(self):
            self.executed = []
            self.executemany_calls = []
            self._rows = list(rows)
            self._fetchone = fetchone if fetchone is not None else (
                rows[0] if rows else None
            )
            self.connection = None

        def execute(self, query, params=()):
            if isinstance(query, str):
                text = query.strip()
            else:
                text = str(query).strip()
            self.executed.append((text, params))
            return self

        def executemany(self, query, seq):
            if isinstance(query, str):
                text = query.strip()
            else:
                text = str(query).strip()
            self.executemany_calls.append((text, list(seq)))

        def fetchall(self):
            return list(self._rows)

        def fetchone(self):
            return self._fetchone

        def close(self):
            pass

    class ConnectionStub:
        def __init__(self):
            self.cursor_instance = CursorStub()
            self.commits = 0

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            self.commits += 1

        def close(self):
            pass

    connection = ConnectionStub()
    monkeypatch.setattr(cc.sqlite3, "connect", lambda *_a, **_kw: connection)
    return connection


class _Telemetry:
    def __init__(self, original, cleaned, segments):
        self.original_length = original
        self.cleaned_length = cleaned
        self.segments_removed = segments
        self.processing_time = 0.05
        self.metadata = {}
        self.removed_segments = [
            {
                "pattern_type": "footer",
                "confidence": 0.92,
                "position": 123,
                "length": original - cleaned,
                "text": "footer text",
            }
        ]


class _Cleaner:
    def __init__(self, *_, **__):
        self.calls = []

    def clean_content(self, *, content, domain, article_id, dry_run):
        self.calls.append((domain, article_id, dry_run))
        telemetry = _Telemetry(len(content), len(content) - 5, 1)
        return content[:-5], telemetry


def test_analyze_domains_no_filtered_domains(monkeypatch, runner):
    _install_sqlite_stub(monkeypatch, [])
    monkeypatch.setattr(cc, "ImprovedContentCleaner", lambda **_: _Cleaner())

    result = runner.invoke(
        cc.content_cleaning,
        ["analyze-domains", "--min-articles", "2"],
    )
    assert result.exit_code == 0
    assert "No domains found" in result.output


def test_analyze_domains_with_results(monkeypatch, runner, tmp_path):
    articles = [
        ("https://example.com/a", "id-1", "Lorem ipsum dolor sit amet", 27),
        ("https://example.com/b", "id-2", "Dolor sit amet lorem ipsum", 27),
    ]
    connection = _install_sqlite_stub(monkeypatch, articles)
    cursor = connection.cursor_instance

    cleaner = _Cleaner()
    monkeypatch.setattr(cc, "ImprovedContentCleaner", lambda **_: cleaner)

    result = runner.invoke(
        cc.content_cleaning,
        [
            "analyze-domains",
            "--min-articles",
            "1",
            "--confidence-threshold",
            "0.8",
        ],
    )

    assert result.exit_code == 0
    assert "Domains analyzed" in result.output
    assert "Articles with boilerplate" in result.output
    assert cleaner.calls
    # Ensure SQL query ran to fetch articles
    assert cursor.executed


def test_list_domains_command_outputs(monkeypatch, runner):
    rows = [
        ("example.com", 5),
        ("news.local", 3),
    ]
    connection = _install_sqlite_stub(monkeypatch, rows)
    cursor = connection.cursor_instance

    result = runner.invoke(
        cc.content_cleaning,
        ["list-domains", "--min-articles", "2"],
    )

    assert result.exit_code == 0
    assert "example.com" in result.output
    assert "news.local" in result.output
    assert cursor.executed


def test_display_analysis_results_prints_segments(capsys):
    results = {
        "domain": "example.com",
        "articles": 5,
        "boilerplate_segments": 2,
        "segments": [
            {
                "confidence_score": 0.91,
                "occurrence_count": 3,
                "avg_position": {"start": 0.1, "end": 0.3},
                "text": "Sample boilerplate",
            }
        ],
    }

    cc._display_analysis_results(results)
    out = capsys.readouterr().out
    assert "DOMAIN ANALYSIS" in out
    assert "Sample boilerplate" in out


def test_display_analysis_results_no_segments(capsys):
    results = {
        "domain": "nomatch.com",
        "articles": 0,
        "boilerplate_segments": 0,
        "segments": [],
    }

    cc._display_analysis_results(results)
    out = capsys.readouterr().out
    assert "No significant boilerplate" in out


def test_register_commands_adds_group():
    cli = click.Group()
    cc.register_commands(cli)
    assert "content-cleaning" in cli.commands


def test_clean_article_handles_missing_record(monkeypatch, runner):
    _install_sqlite_stub(monkeypatch, [], fetchone=None)
    result = runner.invoke(cc.content_cleaning, ["clean-article", "missing"])

    assert result.exit_code == 0
    assert "Article not found" in result.output


def test_clean_article_updates_database(monkeypatch, runner):
    connection = _install_sqlite_stub(
        monkeypatch,
        [],
        fetchone=("https://example.com/article", "Original content"),
    )
    cursor = connection.cursor_instance

    class _CleanerStub(_Cleaner):
        def clean_content(self, *, content, domain, article_id, dry_run):
            self.calls.append((domain, article_id, dry_run))
            telemetry = _Telemetry(len(content), len(content) - 10, 2)
            telemetry.metadata = {"chars_removed": 10}
            return content[:-10], telemetry

    cleaner = _CleanerStub()
    monkeypatch.setattr(cc, "ImprovedContentCleaner", lambda **_: cleaner)

    result = runner.invoke(
        cc.content_cleaning,
        ["clean-article", "article-123", "--show-content"],
    )

    assert result.exit_code == 0
    assert "Article content updated" in result.output
    assert cleaner.calls == [("example.com", "article-123", False)]
    queries = [q for q, _ in cursor.executed]
    assert any("UPDATE articles SET content" in q for q in queries)
    assert connection.commits == 1


def test_apply_cleaning_updates_articles(monkeypatch, runner):
    articles = [
        ("id-1", "https://example.com/a", "Content A"),
        ("id-2", "https://example.com/b", "Content B"),
    ]
    connection = _install_sqlite_stub(monkeypatch, articles)
    cursor = connection.cursor_instance

    class _CleanerStub(_Cleaner):
        def __init__(self):
            super().__init__()

        def clean_content(self, *, content, domain, article_id, dry_run):
            telemetry = _Telemetry(len(content), len(content) - 5, 1)
            telemetry.metadata = {"chars_removed": 5}
            super().clean_content(
                content=content,
                domain=domain,
                article_id=article_id,
                dry_run=dry_run,
            )
            return f"clean-{content}", telemetry

    cleaner = _CleanerStub()
    monkeypatch.setattr(cc, "ImprovedContentCleaner", lambda **_: cleaner)

    result = runner.invoke(
        cc.content_cleaning,
        [
            "apply-cleaning",
            "--limit",
            "2",
            "--verbose",
        ],
    )

    assert result.exit_code == 0
    assert "Articles cleaned" in result.output
    calls = cleaner.calls
    assert {call[1] for call in calls} == {"id-1", "id-2"}
    assert connection.commits == 1
    assert cursor.executemany_calls


def test_clean_content_command_dry_run(monkeypatch, runner):
    connection = _install_sqlite_stub(
        monkeypatch,
        [],
        fetchone=(5, "https://example.com/a", "Example story"),
    )

    class BalancedStub:
        def __init__(self, *_, **__):
            pass

        def process_single_article(self, *, text, domain, article_id, dry_run):
            metadata = {
                "removal_details": [
                    {
                        "pattern_type": "footer",
                        "pattern_name": "Footer",
                        "confidence_score": 0.9,
                        "position": 10,
                        "length": 3,
                        "text": "foo",
                    }
                ],
                "chars_removed": 3,
            }
            return text[:-3], metadata

    monkeypatch.setattr(
        cc, "BalancedBoundaryContentCleaner", BalancedStub
    )

    result = runner.invoke(
        cc.content_cleaning,
        ["clean-content", "5"],
    )

    assert result.exit_code == 0
    assert "Characters removed" in result.output
    assert connection.commits == 0


def test_improved_content_cleaner_fallback(monkeypatch):
    class BrokenBalanced:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("broken")

    monkeypatch.setattr(
        cc, "BalancedBoundaryContentCleaner", BrokenBalanced
    )

    cleaner = cc.ImprovedContentCleaner(db_path="missing.db")
    content, telemetry = cleaner.clean_content(
        content="sample", domain="example.com"
    )

    assert content == "sample"
    assert telemetry.segments_removed == 0
