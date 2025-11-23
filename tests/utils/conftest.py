"""Fixtures for utils tests."""

from contextlib import contextmanager

import pytest


@pytest.fixture
def populated_wire_services(cloud_sql_session, monkeypatch):
    """Populate wire_services table with test patterns for PostgreSQL tests.
    
    Uses the PostgreSQL cloud_sql_session fixture and patches DatabaseManager
    so ContentTypeDetector uses the same session.
    """
    from src.models import WireService

    # Clear existing patterns
    cloud_sql_session.query(WireService).delete()

    # Insert test patterns
    patterns = [
        # Dateline patterns (high priority)
        WireService(
            pattern=r"^[A-Z][A-Z\s,\.'\-]+\s*[–—-]\s*\(?AP\)?\s*[–—-]",
            pattern_type="content",
            service_name="Associated Press",
            case_sensitive=False,
            priority=10,
            active=True,
            notes="AP dateline: WASHINGTON (AP) —",
        ),
        WireService(
            pattern=r"^[A-Z][A-Z\s,\.'\-]+\s*\(AP\)\s*[–—-]",
            pattern_type="content",
            service_name="Associated Press",
            case_sensitive=False,
            priority=10,
            active=True,
            notes="AP dateline: CITY (AP) —",
        ),
        WireService(
            pattern=r"^[A-Z][A-Z\s,\.'\-]+\s*\(Reuters\)\s*[–—-]",
            pattern_type="content",
            service_name="Reuters",
            case_sensitive=False,
            priority=10,
            active=True,
            notes="Reuters dateline",
        ),
        WireService(
            pattern=r"^[A-Z][A-Z\s,\.'\-]+\s*\(?CNN\)?\s*[–—-]",
            pattern_type="content",
            service_name="CNN",
            case_sensitive=False,
            priority=10,
            active=True,
            notes="CNN dateline",
        ),
        WireService(
            pattern=r"\(CNN\)\s*[–—-]",
            pattern_type="content",
            service_name="CNN",
            case_sensitive=False,
            priority=15,
            active=True,
            notes="CNN inline",
        ),
        WireService(
            pattern=r"^[A-Z][A-Z\s,\.'\-]+\s*\(AFP\)\s*[–—-]",
            pattern_type="content",
            service_name="AFP",
            case_sensitive=False,
            priority=10,
            active=True,
            notes="AFP dateline",
        ),
        WireService(
            pattern=r"Bloomberg News",
            pattern_type="content",
            service_name="Bloomberg",
            case_sensitive=False,
            priority=10,
            active=True,
            notes="Bloomberg News",
        ),
        WireService(
            pattern=r"\([A-Z]{3,5}\)",
            pattern_type="content",
            service_name="Broadcaster",
            case_sensitive=False,
            priority=30,
            active=True,
            notes="Generic broadcaster callsign pattern",
        ),
        # Strong URL patterns
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
            notes="Generic wire",
        ),
        WireService(
            pattern="/stacker/",
            pattern_type="url",
            service_name="Stacker",
            case_sensitive=False,
            priority=20,
            active=True,
            notes="Stacker syndication",
        ),
        # Section patterns (weaker, require additional evidence)
        WireService(
            pattern="/national/",
            pattern_type="url",
            service_name="National Section",
            case_sensitive=False,
            priority=50,
            active=True,
            notes="Requires additional evidence",
        ),
        WireService(
            pattern="/world/",
            pattern_type="url",
            service_name="World Section",
            case_sensitive=False,
            priority=50,
            active=True,
            notes="Requires additional evidence",
        ),
    ]

    for pattern in patterns:
        cloud_sql_session.add(pattern)

    cloud_sql_session.commit()

    # Mock DatabaseManager to use cloud_sql_session
    @contextmanager
    def mock_get_session():
        try:
            yield cloud_sql_session
        finally:
            pass

    class MockDatabaseManager:
        """Mock DatabaseManager that uses the test session."""

        def get_session(self):
            return mock_get_session()

    # Patch DatabaseManager where it's defined
    def mock_db_manager(*args, **kwargs):
        return MockDatabaseManager()

    monkeypatch.setattr(
        "src.models.database.DatabaseManager", mock_db_manager
    )

    yield
    # Cleanup handled by cloud_sql_session rollback


@pytest.fixture
def populated_broadcaster_callsigns(cloud_sql_session, monkeypatch):
    """Populate local_broadcaster_callsigns table for PostgreSQL tests.
    
    Uses the PostgreSQL cloud_sql_session fixture and patches DatabaseManager
    so ContentTypeDetector uses the same session.
    """
    from src.models import LocalBroadcasterCallsign

    # Clear existing callsigns
    cloud_sql_session.query(LocalBroadcasterCallsign).delete()

    # Insert test callsigns
    callsigns = [
        LocalBroadcasterCallsign(
            callsign="KMIZ",
            dataset="missouri",
            station_type="television",
            market_name="Columbia",
            notes="ABC affiliate in Columbia, MO",
        ),
        LocalBroadcasterCallsign(
            callsign="KOMU",
            dataset="missouri",
            station_type="television",
            market_name="Columbia",
            notes="NBC affiliate in Columbia, MO",
        ),
        LocalBroadcasterCallsign(
            callsign="KRCG",
            dataset="missouri",
            station_type="television",
            market_name="Jefferson City",
            notes="CBS affiliate in Jefferson City, MO",
        ),
    ]

    for callsign in callsigns:
        cloud_sql_session.add(callsign)

    cloud_sql_session.commit()

    # Mock DatabaseManager to use cloud_sql_session
    @contextmanager
    def mock_get_session():
        try:
            yield cloud_sql_session
        finally:
            pass

    class MockDatabaseManager:
        """Mock DatabaseManager that uses the test session."""

        def get_session(self):
            return mock_get_session()

    # Patch DatabaseManager where it's defined
    def mock_db_manager(*args, **kwargs):
        return MockDatabaseManager()

    monkeypatch.setattr(
        "src.models.database.DatabaseManager", mock_db_manager
    )

    yield
    # Cleanup handled by cloud_sql_session rollback


@pytest.fixture(scope="function", autouse=True)
def populate_wire_service_patterns():
    """Populate wire_services table with test patterns.

    Uses the SQLite in-memory database that's configured in tests/conftest.py.
    Each test gets a fresh set of patterns.
    """
    from src.models import Base, WireService
    from src.models.database import DatabaseManager

    db = DatabaseManager()

    # Get engine and create all tables if they don't exist
    engine = db.engine
    Base.metadata.create_all(bind=engine)

    with db.get_session() as session:
        # Clear existing patterns
        session.query(WireService).delete()

        # Insert test patterns
        patterns = [
            # Dateline patterns (high priority)
            WireService(
                pattern=r"^[A-Z][A-Z\s,\.'\-]+\s*[–—-]\s*\(?AP\)?\s*[–—-]",
                pattern_type="content",
                service_name="Associated Press",
                case_sensitive=False,
                priority=10,
                active=True,
                notes="AP dateline: WASHINGTON (AP) —",
            ),
            WireService(
                pattern=r"^[A-Z][A-Z\s,\.'\-]+\s*\(AP\)\s*[–—-]",
                pattern_type="content",
                service_name="Associated Press",
                case_sensitive=False,
                priority=10,
                active=True,
                notes="AP dateline: CITY (AP) —",
            ),
            WireService(
                pattern=r"^[A-Z][A-Z\s,\.'\-]+\s*\(Reuters\)\s*[–—-]",
                pattern_type="content",
                service_name="Reuters",
                case_sensitive=False,
                priority=10,
                active=True,
                notes="Reuters dateline",
            ),
            WireService(
                pattern=r"^[A-Z][A-Z\s,\.'\-]+\s*\(?CNN\)?\s*[–—-]",
                pattern_type="content",
                service_name="CNN",
                case_sensitive=False,
                priority=10,
                active=True,
                notes="CNN dateline",
            ),
            WireService(
                pattern=r"\(CNN\)\s*[–—-]",
                pattern_type="content",
                service_name="CNN",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="CNN inline",
            ),
            WireService(
                pattern=r"^[A-Z][A-Z\s,\.'\-]+\s*\(AFP\)\s*[–—-]",
                pattern_type="content",
                service_name="AFP",
                case_sensitive=False,
                priority=10,
                active=True,
                notes="AFP dateline",
            ),
            # Strong URL patterns
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
                notes="Generic wire",
            ),
            WireService(
                pattern="/stacker/",
                pattern_type="url",
                service_name="Stacker",
                case_sensitive=False,
                priority=20,
                active=True,
                notes="Stacker syndication",
            ),
            # Section patterns (weaker, require additional evidence)
            WireService(
                pattern="/national/",
                pattern_type="url",
                service_name="National Section",
                case_sensitive=False,
                priority=50,
                active=True,
                notes="Requires additional evidence",
            ),
            WireService(
                pattern="/world/",
                pattern_type="url",
                service_name="World Section",
                case_sensitive=False,
                priority=50,
                active=True,
                notes="Requires additional evidence",
            ),
        ]

        for pattern in patterns:
            session.add(pattern)

        session.commit()

    yield
