"""Pytest-wide fixtures and hooks for NewsCrawler tests."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from coverage import Coverage
from coverage.exceptions import CoverageException
from sqlalchemy import create_engine

from src.telemetry.store import TelemetryStore

# Force tests to use SQLite instead of PostgreSQL/Cloud SQL
# Set BEFORE any imports of src.config to prevent loading production settings
# Tests that need Cloud SQL/PostgreSQL can set PYTEST_KEEP_DB_ENV=true
if "USE_CLOUD_SQL_CONNECTOR" not in os.environ:
    os.environ["USE_CLOUD_SQL_CONNECTOR"] = "false"
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
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
    MODULE_COVERAGE_THRESHOLDS = {
        Path("src/utils/byline_cleaner.py"): 80.0,
        Path("src/utils/content_cleaner_balanced.py"): 80.0,
    }


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
    from src.models.telemetry_orm import Base as TelemetryBase

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

    # Create tables if they don't exist (for SQLite in-memory tests)
    Base.metadata.create_all(bind=engine)

    with db.get_session() as session:
        # Check if patterns already exist (avoid duplicates in nested tests)
        existing_count = session.query(WireService).count()
        if existing_count > 0:
            return

        # Insert wire service patterns (same as migration 259bc609c6a3)
        patterns = [
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
            # Section patterns (weaker signals, require additional evidence)
            WireService(
                pattern="/national/",
                pattern_type="url",
                service_name="National Section",
                case_sensitive=False,
                priority=50,
                active=True,
                notes="National news section - requires additional evidence",
            ),
            WireService(
                pattern="/world/",
                pattern_type="url",
                service_name="World Section",
                case_sensitive=False,
                priority=50,
                active=True,
                notes="World news section - requires additional evidence",
            ),
        ]

        for wire_service in patterns:
            session.add(wire_service)

        session.commit()
