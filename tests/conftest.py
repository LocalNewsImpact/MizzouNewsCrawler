"""Pytest-wide fixtures and hooks for NewsCrawler tests."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from coverage import Coverage
from coverage.exceptions import CoverageException

# Force tests to use SQLite instead of PostgreSQL/Cloud SQL
# Set BEFORE any imports of src.config to prevent loading production settings
# Tests that need Cloud SQL/PostgreSQL can set PYTEST_KEEP_DB_ENV=true
if "USE_CLOUD_SQL_CONNECTOR" not in os.environ:
    os.environ["USE_CLOUD_SQL_CONNECTOR"] = "false"
#: The directory holding this session's SQLite database, or None when
#: DATABASE_URL was set from outside (CI's Postgres, or a developer
#: pointing the suite somewhere).
TEST_DB_DIR: str | None = None

if "DATABASE_URL" not in os.environ:
    # A file, so every DatabaseManager() in a session shares one database
    # -- and a NEW directory per session, because the name used to be
    # fixed: `<tmp>/test_news_crawler.db`, one database for every
    # checkout and every run on the machine.
    #
    # A copy of it left unwritable by an earlier run made the next run
    # fail during COLLECTION, with "attempt to write a readonly
    # database" reported against
    # tests/integration/test_work_queue_integration.py -- a file that
    # was neither the cause nor even selected, because the import that
    # touched the database happened to be in it. Three pushes were
    # rejected by the pre-push hook before the leftover was found.
    #
    # The cleanup below removes the directory, and `atexit` repeats it,
    # because a session that is interrupted never reaches a fixture's
    # teardown and that is how the leftovers were made.
    import atexit
    import shutil
    import tempfile

    TEST_DB_DIR = tempfile.mkdtemp(prefix="news-crawler-tests-")
    atexit.register(shutil.rmtree, TEST_DB_DIR, ignore_errors=True)
    test_db_path = os.path.join(TEST_DB_DIR, "news_crawler.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path}"
# Clear PostgreSQL env vars that might cause unwanted connections
# Prevents src.config from building PostgreSQL URL when running tests locally
for key in [
    "DATABASE_HOST",
    "DATABASE_PORT",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
    "CLOUD_SQL_INSTANCE",
]:
    if key in os.environ and os.environ.get("PYTEST_KEEP_DB_ENV") != "true":
        os.environ.pop(key, None)

# Force telemetry to use synchronous writes in tests to avoid background
# thread issues and make tests deterministic
if "TELEMETRY_ASYNC_WRITES" not in os.environ:
    os.environ["TELEMETRY_ASYNC_WRITES"] = "false"

pytest_plugins = [
    "tests.helpers.sqlite",
    "tests.helpers.filesystem",
    # Export backend fixtures via a dedicated plugin wrapper so integration
    # tests can access cloud_sql_* fixtures without double-registration.
    "tests.plugins.backend_fixtures",
]


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_database():
    """Remove this session's SQLite database when the session ends.

    The whole directory goes, not just the file: SQLite writes `-wal`
    and `-shm` beside it, and a directory removed whole cannot leave one
    of them behind.

    Nothing is removed when DATABASE_URL came from outside -- that is
    CI's Postgres, or somebody's own database, and neither is this
    fixture's to delete.
    """
    yield
    import shutil

    if TEST_DB_DIR:
        shutil.rmtree(TEST_DB_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def mock_extraction_method_lookup(request, monkeypatch):
    """Mock _get_domain_extraction_method to prevent DB calls in tests.

    This autouse fixture prevents the ContentExtractor from making database
    queries when checking a domain's extraction method.
    By default, returns ('http', None) meaning standard HTTP extraction.

    Tests that specifically want to test special extraction methods should
    override this by providing their own mock.

    This fixture does NOT apply to tests marked with @pytest.mark.integration,
    as those tests need to exercise real database behavior.
    """
    # Skip mocking for integration tests that need real DB behavior
    if "integration" in request.keywords:
        return

    from src.crawler import ContentExtractor

    monkeypatch.setattr(
        ContentExtractor,
        "_get_domain_extraction_method",
        lambda self, domain: ("http", None),
    )


@pytest.fixture(autouse=True)
def disable_real_selenium(request, monkeypatch):
    """Prevent tests from spawning a real Chrome instance via Selenium.

    Tests that legitimately need Selenium can opt in with
    @pytest.mark.enable_selenium or by manually monkeypatching the
    SELENIUM_AVAILABLE flag inside the test body.
    """

    if "enable_selenium" in request.keywords:
        return

    import src.crawler as crawler_module

    if "integration" in request.keywords:
        # Integration tests stub Selenium methods but still need the flag set
        # so that fallback logic executes the patched routines.
        monkeypatch.setattr(crawler_module, "SELENIUM_AVAILABLE", True)
        return

    monkeypatch.setattr(crawler_module, "SELENIUM_AVAILABLE", False)


@pytest.fixture(autouse=True)
def block_external_network(request, monkeypatch):
    """Fail fast if a unit test makes a real outbound network connection.

    Discovery/extraction code can accidentally reach the network (e.g.
    newspaper4k fetching a source homepage during process_source), which is
    slow and has hung CI. This guard blocks connections to non-loopback hosts
    so such calls surface immediately with a clear message instead of stalling.

    Loopback (localhost / 127.0.0.1 / ::1) stays allowed so tests can use a
    local database or HTTP stub. Exempted entirely: tests that legitimately use
    the network or a real remote service — integration, postgres, e2e,
    enable_selenium, proxy — and any test marked @pytest.mark.allow_network.
    """
    exempt = (
        "integration",
        "postgres",
        "e2e",
        "enable_selenium",
        "proxy",
        "allow_network",
    )
    if any(marker in request.keywords for marker in exempt):
        return

    import socket

    allowed_hosts = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _is_blocked(address):
        # Non-tuple addresses (AF_UNIX paths) are local IPC — allow them.
        if not isinstance(address, tuple) or not address:
            return False
        return address[0] not in allowed_hosts

    def _guard(real_method):
        def _inner(self, address, *args, **kwargs):
            if _is_blocked(address):
                raise RuntimeError(
                    f"Blocked real network connection to {address!r} in a unit "
                    "test. Mock the network call, or mark the test "
                    "@pytest.mark.allow_network (or @pytest.mark.integration) "
                    "if it genuinely needs the network."
                )
            return real_method(self, address, *args, **kwargs)

        return _inner

    monkeypatch.setattr(socket.socket, "connect", _guard(real_connect))
    monkeypatch.setattr(socket.socket, "connect_ex", _guard(real_connect_ex))


@pytest.fixture(autouse=True)
def mock_proxy_router_client(request, monkeypatch):
    """Prevent unit tests from reaching real Firestore via proxy_router.

    google-cloud-firestore talks gRPC, which has its own C-level networking
    that block_external_network's socket.socket.connect() patch cannot see
    -- so without this, any test that exercises code wired to proxy_router
    (discovery.py, url_verification.py, crawler/__init__.py's domain
    sessions) silently makes a real Firestore call whenever the environment
    happens to have ADC credentials (e.g. from `gcloud auth` on a dev
    machine), which is slow and can write real rows into production
    Firestore. Forcing _get_client() to None makes every such call take the
    same static-fallback path deterministically.

    ONLY tests marked `proxy` are exempt -- they manage their own client
    mocking or run against the Firestore emulator. A blanket `integration`
    exemption used to exist here and was a live regression: the
    postgres+integration extractor telemetry tests silently made real
    production-Firestore round-trips on every simulated request (272s and
    240s per test instead of ~1s -- 88% of the whole postgres suite's
    runtime) and wrote junk rows into the production proxy_domain_status
    collection. Integration tests that genuinely need real/emulated
    Firestore must also carry the `proxy` marker.
    """
    if "proxy" in request.keywords:
        return

    from src.crawler import proxy_router

    monkeypatch.setattr(proxy_router, "_get_client", lambda: None)


@pytest.fixture
def clean_app_state():
    """Fixture to ensure FastAPI app.state is clean between tests.

    This is useful for backend tests that interact with the FastAPI
    application lifecycle. It ensures that any resources attached to
    app.state during one test don't leak into subsequent tests.

    Usage:
        def test_something(clean_app_state):
            from backend.app.main import app
            # Test code that modifies app.state
            # Cleanup happens automatically after test
    """
    from backend.app.main import app

    # Store original state
    original_state = {}
    for key in dir(app.state):
        if not key.startswith("_"):
            original_state[key] = getattr(app.state, key, None)

    yield app

    # Restore original state and clean up any new attributes
    current_keys = [k for k in dir(app.state) if not k.startswith("_")]
    for key in current_keys:
        if key in original_state:
            setattr(app.state, key, original_state[key])
        else:
            # New attribute added during test, remove it
            try:
                delattr(app.state, key)
            except AttributeError:
                pass

    # Also clear any dependency overrides
    app.dependency_overrides.clear()


# ensure spacing per PEP8


# Module-level coverage thresholds expressed as percentages. The paths are
# relative to the project root (session.config.rootpath) so the check works
# both locally and in CI environments.

MODULE_COVERAGE_THRESHOLDS: dict[Path, float]

if os.environ.get("PYTEST_DISABLE_MODULE_THRESHOLDS") == "1":
    MODULE_COVERAGE_THRESHOLDS = {}
else:
    MODULE_COVERAGE_THRESHOLDS = {}


def _resolve_threshold_paths(root: Path) -> dict[Path, float]:
    """Return absolute module paths mapped to their required coverage."""
    return {
        root / relative_path: threshold
        for relative_path, threshold in MODULE_COVERAGE_THRESHOLDS.items()
    }


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the test session if any module falls below its coverage floor."""
    cov_plugin = session.config.pluginmanager.get_plugin("_cov")
    if cov_plugin is None:
        # Coverage collection was not requested (e.g. ``pytest --no-cov``).
        return

    cov_controller = getattr(cov_plugin, "cov_controller", None)
    cov: Coverage | None
    if cov_controller:
        cov = getattr(cov_controller, "cov", None)
    else:
        cov = None
    if cov is None:
        # Coverage measurements are unavailable, nothing to enforce.
        return

    try:
        cov.load()
    except CoverageException:
        return

    project_root = Path(session.config.rootpath).resolve()
    failures: list[str] = []
    threshold_map = _resolve_threshold_paths(project_root)

    for module_path, threshold in threshold_map.items():
        if not module_path.exists():
            failures.append(f"{module_path.relative_to(project_root)} missing on disk")
            continue

        buffer = io.StringIO()
        try:
            percent = cov.report(morfs=[str(module_path)], file=buffer)
        except CoverageException as exc:  # pragma: no cover - defensive guard
            failures.append(
                f"{module_path.relative_to(project_root)} coverage unavailable: {exc}"
            )
            continue

        if percent < threshold:
            failures.append(
                f"{module_path.relative_to(project_root)} "
                f"{percent:.2f}% < {threshold:.2f}%"
            )

    if failures:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(
                "Module coverage thresholds not met:", red=True, bold=True
            )
            for message in failures:
                reporter.write_line(f"  {message}", red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture
def telemetry_store_with_migrations(tmp_path):
    """Create a TelemetryStore with proper Cloud SQL schema via SQLAlchemy ORM.

    This fixture ensures tests use the same schema as production by using
    the SQLAlchemy ORM models to create all telemetry tables.

    Returns:
        TelemetryStore: A store with all tables properly created.
    """
    from sqlalchemy import create_engine

    from src.models.telemetry_orm import Base as TelemetryBase
    from src.telemetry.store import TelemetryStore

    db_path = tmp_path / "telemetry.db"
    db_url = f"sqlite:///{db_path}"

    # Create engine
    engine = create_engine(db_url, echo=False)

    # Create all telemetry tables using ORM
    TelemetryBase.metadata.create_all(engine)

    # Create store
    store = TelemetryStore(database=db_url, async_writes=False, engine=engine)

    yield store

    # Cleanup
    store.shutdown()
    engine.dispose()


@pytest.fixture(scope="function", autouse=True)
def populate_wire_service_patterns():
    """Populate wire_services table with test patterns for wire detection tests.

    This fixture automatically runs before each test and populates the wire_services
    table with dateline and URL patterns needed for content type detection.
    """
    from src.models import Base, WireService
    from src.models.database import DatabaseManager

    db = DatabaseManager()
    engine = db.engine

    # SQLite only. This is here for in-memory tests that have no schema of
    # their own; against a real Postgres it created all 32 ORM tables in
    # whatever DATABASE_URL pointed at, before any test ran -- so alembic
    # then failed with "relation already exists" and the integration tests
    # could not be run locally at all. They ran in CI, where this fixture
    # reaches a different database, which is exactly how a test suite
    # comes to pass in one place and fail in the other.
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(bind=engine)

    # Clear ContentTypeDetector cache FIRST to ensure fresh patterns are loaded
    # The cache is class-level and persists across test functions
    from src.utils.content_type_detector import ContentTypeDetector

    ContentTypeDetector._wire_patterns_cache = None
    ContentTypeDetector._wire_patterns_timestamp = None
    if hasattr(ContentTypeDetector, "_pattern_cache_by_type"):
        ContentTypeDetector._pattern_cache_by_type = {}
    if hasattr(ContentTypeDetector, "_pattern_timestamp_by_type"):
        ContentTypeDetector._pattern_timestamp_by_type = {}

    with db.get_session() as session:
        # The table may not be there yet. Against Postgres the schema is
        # built by alembic, and this autouse fixture runs before the
        # fixture that runs it -- so on a clean database `wire_services`
        # does not exist, and an error here failed every integration test
        # for a reason that had nothing to do with any of them.
        #
        # Nothing that needs these patterns runs before the schema does.
        from sqlalchemy import inspect as _inspect

        if not _inspect(engine).has_table(WireService.__tablename__):
            return

        # Check if patterns already exist (avoid duplicates in nested tests)
        existing_count = session.query(WireService).count()
        if existing_count > 0:
            return

        # Insert wire service patterns (same as migration 259bc609c6a3 + f224b4c09ef3)
        patterns = [
            # ==================== CONTENT PATTERNS (Datelines) ====================
            # AP dateline patterns
            WireService(
                pattern=r"^[A-Z][A-Z\s,\.''\-]+\s*[–—-]\s*\(?AP\)?\s*[–—-]",
                pattern_type="content",
                service_name="Associated Press",
                case_sensitive=False,
                priority=10,
                active=True,
                notes="AP dateline pattern: CITY (AP) —",
            ),
            WireService(
                pattern=r"^[A-Z][A-Z\s,\.''\-]+\s*\(AP\)\s*[–—-]",
                pattern_type="content",
                service_name="Associated Press",
                case_sensitive=False,
                priority=10,
                active=True,
                notes="AP dateline pattern: CITY (AP) —",
            ),
            # Reuters dateline patterns
            WireService(
                pattern=r"^[A-Z][A-Z\s,\.''\-]+\s*\(Reuters\)\s*[–—-]",
                pattern_type="content",
                service_name="Reuters",
                case_sensitive=False,
                priority=10,
                active=True,
                notes="Reuters dateline pattern: CITY (Reuters) —",
            ),
            # CNN dateline patterns
            WireService(
                pattern=r"^[A-Z][A-Z\s,\.''\-]+\s*\(?CNN\)?\s*[–—-]",
                pattern_type="content",
                service_name="CNN",
                case_sensitive=False,
                priority=10,
                active=True,
                notes="CNN dateline pattern: CITY (CNN) —",
            ),
            WireService(
                pattern=r"\(CNN\)\s*[–—-]",
                pattern_type="content",
                service_name="CNN",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="CNN inline dateline",
            ),
            # AFP dateline patterns
            WireService(
                pattern=r"^[A-Z][A-Z\s,\.''\-]+\s*\(AFP\)\s*[–—-]",
                pattern_type="content",
                service_name="AFP",
                case_sensitive=False,
                priority=10,
                active=True,
                notes="AFP dateline pattern: CITY (AFP) —",
            ),
            # Copyright patterns
            WireService(
                pattern=r"Copyright.*?(?:The\s+)?Associated Press",
                pattern_type="content",
                service_name="Associated Press",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="AP copyright in closing",
            ),
            WireService(
                pattern=r"©.*?(?:The\s+)?NPR",
                pattern_type="content",
                service_name="NPR",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="NPR copyright in closing",
            ),
            WireService(
                pattern=r"Copyright.*?WAVE",
                pattern_type="content",
                service_name="WAVE",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="WAVE copyright in closing",
            ),
            # Attribution patterns
            WireService(
                pattern=r"\btold AFP\b",
                pattern_type="content",
                service_name="AFP",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="AFP attribution pattern (told AFP)",
            ),
            # ==================== URL PATTERNS ====================
            # Strong URL patterns (explicit wire paths)
            WireService(
                pattern="/ap-",
                pattern_type="url",
                service_name="Associated Press",
                case_sensitive=False,
                priority=20,
                active=True,
                notes="AP URL segment",
            ),
            WireService(
                pattern="/wire/",
                pattern_type="url",
                service_name="Wire Service",
                case_sensitive=False,
                priority=20,
                active=True,
                notes="Generic wire URL segment",
            ),
            WireService(
                pattern="/stacker/",
                pattern_type="url",
                service_name="Stacker",
                case_sensitive=False,
                priority=20,
                active=True,
                notes="Stacker syndication URL",
            ),
            # Section patterns
            WireService(
                pattern="/national/",
                pattern_type="url",
                service_name="National Section",
                case_sensitive=False,
                priority=50,
                active=True,
                notes="National news section",
                exclude_domains="nytimes.com,washingtonpost.com,latimes.com",
            ),
            WireService(
                pattern="/world/",
                pattern_type="url",
                service_name="World Section",
                case_sensitive=False,
                priority=50,
                active=True,
                notes="World news section",
                exclude_domains="nytimes.com,washingtonpost.com,latimes.com",
            ),
            # ==================== AUTHOR PATTERNS ====================
            # Explicit wire service names (STRONGEST SIGNALS)
            WireService(
                pattern=r"\bAssociated Press\b",
                pattern_type="author",
                service_name="Associated Press",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="AP full name in byline",
            ),
            WireService(
                pattern=r"\bAP\b",
                pattern_type="author",
                service_name="Associated Press",
                case_sensitive=False,
                priority=10,
                active=True,
                notes="AP abbreviation in byline",
            ),
            WireService(
                pattern=r"\bReuters\b",
                pattern_type="author",
                service_name="Reuters",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="Reuters in byline",
            ),
            WireService(
                pattern=r"\bCNN\b",
                pattern_type="author",
                service_name="CNN",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="CNN in byline",
            ),
            WireService(
                pattern=r"\bAFP\b",
                pattern_type="author",
                service_name="AFP",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="AFP in byline",
            ),
            WireService(
                pattern=r"\bUSA TODAY\b",
                pattern_type="author",
                service_name="USA TODAY",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="USA TODAY in byline",
            ),
            WireService(
                pattern=r"\bStates Newsroom\b",
                pattern_type="author",
                service_name="States Newsroom",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="States Newsroom syndication",
            ),
            WireService(
                pattern=r"\bKansas Reflector\b",
                pattern_type="author",
                service_name="States Newsroom",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="Kansas Reflector (States Newsroom)",
            ),
            WireService(
                pattern=r"\bThe Missouri Independent\b",
                pattern_type="author",
                service_name="The Missouri Independent",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="Missouri Independent in byline",
            ),
            WireService(
                pattern=r"\bMissouri Independent\b",
                pattern_type="author",
                service_name="The Missouri Independent",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="Missouri Independent (short form)",
            ),
            WireService(
                pattern=r"\bWAVE\b",
                pattern_type="author",
                service_name="WAVE",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="WAVE in byline",
            ),
            WireService(
                pattern=r"\bNPR\b",
                pattern_type="author",
                service_name="NPR",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="NPR in byline",
            ),
            WireService(
                pattern=r"\bStacker\b",
                pattern_type="author",
                service_name="Stacker",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="Stacker in byline",
            ),
            # Additional author patterns needed by tests
            WireService(
                pattern=r"\bAP Staff\b",
                pattern_type="author",
                service_name="Associated Press",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="AP Staff in byline",
            ),
            WireService(
                pattern=r"\bAfp Afp\b",
                pattern_type="author",
                service_name="AFP",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="AFP AFP variant in byline",
            ),
            WireService(
                pattern=r"\bAfp$",
                pattern_type="author",
                service_name="AFP",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="Name ending with AFP",
            ),
            WireService(
                pattern=r"\bWAVE3\b",
                pattern_type="author",
                service_name="WAVE",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="Stacker syndication",
            ),
            # Additional author pattern variants
            WireService(
                pattern=r"\bAP Staff\b",
                pattern_type="author",
                service_name="Associated Press",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="AP Staff byline",
            ),
            WireService(
                pattern=r"\bAfp Afp\b",
                pattern_type="author",
                service_name="AFP",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="AFP repeated name pattern",
            ),
            WireService(
                pattern=r"\sAfp$",
                pattern_type="author",
                service_name="AFP",
                case_sensitive=False,
                priority=8,
                active=True,
                notes="Name ending with AFP",
            ),
            WireService(
                pattern=r"\bWAVE3\b",
                pattern_type="author",
                service_name="WAVE",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="WAVE3 variant",
            ),
            # Copyright patterns (content)
            WireService(
                pattern=r"Copyright\s+\d{4}\s+(?:The\s+)?Associated Press",
                pattern_type="content",
                service_name="Associated Press",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="AP copyright statement",
            ),
            WireService(
                pattern=r"©\s*\d{4}\s+(?:The\s+)?NPR",
                pattern_type="content",
                service_name="NPR",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="NPR copyright statement",
            ),
            WireService(
                pattern=r"Copyright\s+\d{4}\s+WAVE",
                pattern_type="content",
                service_name="WAVE",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="WAVE copyright statement",
            ),
            # Attribution patterns (content)
            WireService(
                pattern=r"\btold\s+AFP\b",
                pattern_type="content",
                service_name="AFP",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="AFP attribution pattern (told AFP)",
            ),
            WireService(
                pattern=r"first appeared in the Kansas Reflector",
                pattern_type="content",
                service_name="States Newsroom",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="States Newsroom syndication attribution",
            ),
        ]

        for wire_service in patterns:
            session.add(wire_service)

        session.commit()

        # Populate exclude_domains based on service_name
        # (mirrors migration cea12b602254_add_exclude_domains_to_wire_services.py)
        exclude_domains_map = {
            "Associated Press": "apnews.com",
            "Reuters": "reuters.com",
            "AFP": "afp.com",
            "Bloomberg": "bloomberg.com",
            "NPR": "npr.org",
            "CNN": "cnn.com",
            "Fox News": "foxnews.com",
            "ABC News": "abcnews.go.com",
            "CBS News": "cbsnews.com",
            "NBC News": "nbcnews.com",
            "USA TODAY": "usatoday.com",
            "States Newsroom": "statesnewsroom.org,missouriindependent.com,kansasreflector.com",
            "Missouri Independent": "missouriindependent.com",
            "Kansas Reflector": "kansasreflector.com",
            "Missouri News Network": "komu.com,kbia.org,columbiamissourian.com,missouribusinessalert.com",
            "WAVE": "wave3.com",
        }
        for service_name, domains in exclude_domains_map.items():
            session.query(WireService).filter(
                WireService.service_name == service_name
            ).update({WireService.exclude_domains: domains})
        session.commit()


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Directory-level marker rules — the single source of truth that replaced
    the hand-maintained --ignore lists in ci.yml (which had drifted from the
    local pre-push hook: local ran a superset of CI, and files like
    tests/test_gazetteer_integration.py were silently invisible to CI).

    Every test under tests/docker/ is a docker test; everything under
    tests/scripts/ is a local-script test unless it already carries an
    infrastructure marker (postgres/integration). Marker-based selection in
    ci.yml and the pre-push hook then produces IDENTICAL test sets.
    """
    import pathlib

    for item in items:
        rel = pathlib.Path(str(item.fspath)).as_posix()
        if "/tests/docker/" in rel:
            item.add_marker(pytest.mark.docker)
        elif "/tests/scripts/" in rel:
            existing = {m.name for m in item.iter_markers()}
            if not ({"postgres", "integration"} & existing):
                item.add_marker(pytest.mark.local_scripts)
