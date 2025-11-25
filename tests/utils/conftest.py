"""Fixtures for utils tests."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def wire_detection_test_session():
    """Create an in-memory SQLite session with wire service patterns for testing."""
    from src.models import Base, WireService
    from src.utils.wire_reporters import (
        clear_wire_reporters_cache,
        set_wire_reporters_cache,
    )

    # Clear any cached wire reporters
    clear_wire_reporters_cache()

    # Create in-memory SQLite engine
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)

    # Create session
    Session = sessionmaker(bind=engine)
    session = Session()

    # Insert wire service patterns (URL and content detection)
    patterns = [
        # Content patterns (byline/content matching)
        WireService(
            pattern=r"\b(AFP|Agence France-Presse)\b",
            pattern_type="content",
            service_name="AFP",
            case_sensitive=False,
            priority=20,
            active=True,
        ),
        WireService(
            pattern=r"\b(AP|A\.P\.)\b",
            pattern_type="content",
            service_name="Associated Press",
            case_sensitive=False,
            priority=20,
            active=True,
        ),
        WireService(
            pattern=r"\b(ASSOCIATED PRESS|Associated Press)\b",
            pattern_type="content",
            service_name="Associated Press",
            case_sensitive=True,
            priority=20,
            active=True,
        ),
        WireService(
            pattern=r"\b(CNN|C\.N\.N\.)\b",
            pattern_type="content",
            service_name="CNN",
            case_sensitive=False,
            priority=20,
            active=True,
        ),
        WireService(
            pattern=r"\bREUTERS\b",
            pattern_type="content",
            service_name="Reuters",
            case_sensitive=False,
            priority=20,
            active=True,
        ),
        WireService(
            pattern=r"\b(Reuters)\b",
            pattern_type="content",
            service_name="Reuters",
            case_sensitive=True,
            priority=20,
            active=True,
        ),
        WireService(
            pattern=r"\bStacker\b",
            pattern_type="content",
            service_name="Stacker",
            case_sensitive=False,
            priority=20,
            active=True,
        ),
        WireService(
            pattern=r"\b(Bloomberg|BLOOMBERG)\b",
            pattern_type="content",
            service_name="Bloomberg",
            case_sensitive=False,
            priority=25,
            active=True,
        ),
        WireService(
            pattern=r"\bLos Angeles Times\b",
            pattern_type="content",
            service_name="Los Angeles Times",
            case_sensitive=True,
            priority=25,
            active=True,
        ),
        WireService(
            pattern=r"\b(NPR|N\.P\.R\.)\b",
            pattern_type="content",
            service_name="NPR",
            case_sensitive=False,
            priority=25,
            active=True,
        ),
        WireService(
            pattern=r"\b(PBS|P\.B\.S\.)\b",
            pattern_type="content",
            service_name="PBS",
            case_sensitive=False,
            priority=25,
            active=True,
        ),
        WireService(
            pattern=r"\b(Kansas\s+Reflector|KansasReflector|kansasreflector)\b",
            pattern_type="content",
            service_name="States Newsroom",
            case_sensitive=False,
            priority=25,
            active=True,
        ),
        WireService(
            pattern=r"\b(States\s+Newsroom|StatesNewsroom|States-Newsroom)\b",
            pattern_type="content",
            service_name="States Newsroom",
            case_sensitive=False,
            priority=25,
            active=True,
        ),
        WireService(
            pattern=r"\b(The\s+Missouri\s+Independent|Missouri\s+Independent)\b",
            pattern_type="content",
            service_name="The Missouri Independent",
            case_sensitive=False,
            priority=25,
            active=True,
        ),
        WireService(
            pattern=r"\bThe New York Times\b",
            pattern_type="content",
            service_name="The New York Times",
            case_sensitive=True,
            priority=25,
            active=True,
        ),
        WireService(
            pattern=r"\bThe Washington Post\b",
            pattern_type="content",
            service_name="The Washington Post",
            case_sensitive=True,
            priority=25,
            active=True,
        ),
        WireService(
            pattern=r"\bUSA TODAY\b",
            pattern_type="content",
            service_name="USA TODAY",
            case_sensitive=True,
            priority=25,
            active=True,
        ),
        WireService(
            pattern=r"\bWall Street Journal\b",
            pattern_type="content",
            service_name="Wall Street Journal",
            case_sensitive=True,
            priority=25,
            active=True,
        ),
        WireService(
            pattern=r"\b(WAVE|Wave|WAVE3|wave3)\b",
            pattern_type="content",
            service_name="WAVE",
            case_sensitive=False,
            priority=25,
            active=True,
        ),
        WireService(
            pattern=r"\bGannett\b",
            pattern_type="content",
            service_name="Gannett",
            case_sensitive=True,
            priority=30,
            active=True,
        ),
        WireService(
            pattern=r"\bMcClatchy\b",
            pattern_type="content",
            service_name="McClatchy",
            case_sensitive=True,
            priority=30,
            active=True,
        ),
        WireService(
            pattern=r"\bTribune News Service\b",
            pattern_type="content",
            service_name="Tribune News Service",
            case_sensitive=True,
            priority=30,
            active=True,
        ),
        WireService(
            pattern=r"\b(UPI|U\.P\.I\.)\b",
            pattern_type="content",
            service_name="UPI",
            case_sensitive=False,
            priority=30,
            active=True,
        ),
        # URL patterns - strong signals (wire sections on local sites)
        WireService(
            pattern="/ap-",
            pattern_type="url",
            service_name="Associated Press",
            case_sensitive=False,
            priority=20,
            active=True,
        ),
        WireService(
            pattern="/cnn-",
            pattern_type="url",
            service_name="CNN",
            case_sensitive=False,
            priority=20,
            active=True,
        ),
        WireService(
            pattern="/reuters-",
            pattern_type="url",
            service_name="Reuters",
            case_sensitive=False,
            priority=20,
            active=True,
        ),
        WireService(
            pattern="/stacker/",
            pattern_type="url",
            service_name="Stacker",
            case_sensitive=False,
            priority=20,
            active=True,
        ),
        WireService(
            pattern="/stacker-",
            pattern_type="url",
            service_name="Stacker",
            case_sensitive=False,
            priority=20,
            active=True,
        ),
        WireService(
            pattern="/wire/",
            pattern_type="url",
            service_name="Wire Service",
            case_sensitive=False,
            priority=20,
            active=True,
        ),
        # URL patterns - wire service domains (should be excluded if on own domain)
        WireService(
            pattern="apnews.com",
            pattern_type="url",
            service_name="Associated Press",
            case_sensitive=False,
            priority=25,
            active=True,
        ),
        WireService(
            pattern="cnn.com",
            pattern_type="url",
            service_name="CNN",
            case_sensitive=False,
            priority=25,
            active=True,
        ),
        WireService(
            pattern="reuters.com",
            pattern_type="url",
            service_name="Reuters",
            case_sensitive=False,
            priority=25,
            active=True,
        ),
        WireService(
            pattern="stacker.com",
            pattern_type="url",
            service_name="Stacker",
            case_sensitive=False,
            priority=25,
            active=True,
        ),
        WireService(
            pattern="bloomberg.com",
            pattern_type="url",
            service_name="Bloomberg",
            case_sensitive=False,
            priority=30,
            active=True,
        ),
        WireService(
            pattern="latimes.com",
            pattern_type="url",
            service_name="Los Angeles Times",
            case_sensitive=False,
            priority=30,
            active=True,
        ),
        WireService(
            pattern="npr.org",
            pattern_type="url",
            service_name="NPR",
            case_sensitive=False,
            priority=30,
            active=True,
        ),
        WireService(
            pattern="pbs.org",
            pattern_type="url",
            service_name="PBS",
            case_sensitive=False,
            priority=30,
            active=True,
        ),
        WireService(
            pattern="kansasreflector.com",
            pattern_type="url",
            service_name="States Newsroom",
            case_sensitive=False,
            priority=30,
            active=True,
        ),
        WireService(
            pattern="statesnewsroom.org",
            pattern_type="url",
            service_name="States Newsroom",
            case_sensitive=False,
            priority=30,
            active=True,
        ),
        WireService(
            pattern="missouriindependent.com",
            pattern_type="url",
            service_name="The Missouri Independent",
            case_sensitive=False,
            priority=30,
            active=True,
        ),
        WireService(
            pattern="missouriindependent.org",
            pattern_type="url",
            service_name="The Missouri Independent",
            case_sensitive=False,
            priority=30,
            active=True,
        ),
        WireService(
            pattern="nytimes.com",
            pattern_type="url",
            service_name="The New York Times",
            case_sensitive=False,
            priority=30,
            active=True,
        ),
        WireService(
            pattern="washingtonpost.com",
            pattern_type="url",
            service_name="The Washington Post",
            case_sensitive=False,
            priority=30,
            active=True,
        ),
        WireService(
            pattern="usatoday.com",
            pattern_type="url",
            service_name="USA TODAY",
            case_sensitive=False,
            priority=30,
            active=True,
        ),
        WireService(
            pattern="wsj.com",
            pattern_type="url",
            service_name="Wall Street Journal",
            case_sensitive=False,
            priority=30,
            active=True,
        ),
        WireService(
            pattern="wave3.com",
            pattern_type="url",
            service_name="WAVE",
            case_sensitive=False,
            priority=30,
            active=True,
        ),
        # Geographic scope patterns (weaker signals, require additional evidence)
        WireService(
            pattern="/national/",
            pattern_type="url",
            service_name="National Section",
            case_sensitive=False,
            priority=50,
            active=True,
        ),
        WireService(
            pattern="/world/",
            pattern_type="url",
            service_name="World Section",
            case_sensitive=False,
            priority=50,
            active=True,
        ),
    ]

    for pattern in patterns:
        session.add(pattern)

    session.commit()

    # Set known wire reporters cache (from byline_cleaning_telemetry data)
    # These are bylines flagged as wire service content
    wire_reporters_cache = {
        # AFP reporters
        "afp afp": ("AFP", "high"),
        "afp": ("AFP", "high"),
        # AP reporters - common byline patterns
        "associated press": ("Associated Press", "high"),
        "the associated press": ("Associated Press", "high"),
        "ap": ("Associated Press", "high"),
        # Reuters reporters
        "reuters": ("Reuters", "high"),
        # Stacker
        "stacker": ("Stacker", "high"),
        # CNN - top wire source with 2,467 articles
        "cnn": ("CNN", "high"),
        "cnn wire": ("CNN", "high"),
        "cnn newsource": ("CNN Newsource", "high"),
        # NPR
        "npr": ("NPR", "high"),
        # Bloomberg
        "bloomberg": ("Bloomberg", "high"),
        "bloomberg news": ("Bloomberg", "high"),
    }
    set_wire_reporters_cache(wire_reporters_cache)

    # Mock DatabaseManager to use this session
    @contextmanager
    def mock_get_session():
        try:
            yield session
        finally:
            pass

    class MockDatabaseManager:
        """Mock DatabaseManager that uses the test session."""

        def get_session(self):
            return mock_get_session()

    # Return session and mock manager setup
    yield session, MockDatabaseManager

    # Cleanup
    clear_wire_reporters_cache()
    session.close()
    engine.dispose()


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

    monkeypatch.setattr("src.models.database.DatabaseManager", mock_db_manager)

    yield
    # Cleanup handled by cloud_sql_session rollback


@pytest.fixture
def populated_wire_services(cloud_sql_session, monkeypatch):
    """Populate wire_services table for PostgreSQL integration tests.

    Uses the PostgreSQL cloud_sql_session fixture and patches DatabaseManager
    so ContentTypeDetector uses the same session.
    """
    from src.models import WireService

    # Clear existing patterns
    cloud_sql_session.query(WireService).delete()

    # Insert test wire service patterns
    patterns = [
        # AP patterns
        WireService(
            pattern=r"\(AP\)\s*[—–-]",
            pattern_type="content",
            service_name="Associated Press",
            priority=100,
            case_sensitive=False,
        ),
        # Reuters patterns
        WireService(
            pattern=r"\(Reuters\)\s*[—–-]",
            pattern_type="content",
            service_name="Reuters",
            priority=100,
            case_sensitive=False,
        ),
        # AFP patterns
        WireService(
            pattern=r"\bAfp Afp\b",
            pattern_type="author",
            service_name="AFP",
            priority=80,
            case_sensitive=False,
        ),
        # Bloomberg patterns
        WireService(
            pattern=r"\b(Bloomberg|BLOOMBERG)\b",
            pattern_type="author",
            service_name="Bloomberg",
            priority=80,
            case_sensitive=False,
        ),
        # Generic Broadcaster pattern
        WireService(
            pattern=r"Broadcaster$",
            pattern_type="author",
            service_name="Broadcaster",
            priority=60,
            case_sensitive=False,
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

    monkeypatch.setattr("src.models.database.DatabaseManager", mock_db_manager)

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
            # Author patterns needed by tests
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
                pattern=r"\bStates Newsroom\b",
                pattern_type="author",
                service_name="States Newsroom",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="States Newsroom in byline",
            ),
            WireService(
                pattern=r"\bStates Newsroom$",
                pattern_type="author",
                service_name="States Newsroom",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="Name ending with States Newsroom",
            ),
            WireService(
                pattern=r"\bThe Missouri Independent\b",
                pattern_type="author",
                service_name="The Missouri Independent",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="Missouri Independent syndication",
            ),
            WireService(
                pattern=r"\bUSA TODAY\b",
                pattern_type="author",
                service_name="USA TODAY",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="USA TODAY syndication",
            ),
            WireService(
                pattern=r"\bKansas Reflector\b",
                pattern_type="author",
                service_name="States Newsroom",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="States Newsroom affiliate",
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
                pattern=r"\bReuters Staff\b",
                pattern_type="author",
                service_name="Reuters",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="Reuters Staff byline",
            ),
            WireService(
                pattern=r"\bWAVE3 News\b",
                pattern_type="author",
                service_name="WAVE",
                case_sensitive=False,
                priority=5,
                active=True,
                notes="WAVE3 News byline",
            ),
            # Copyright and attribution patterns
            WireService(
                pattern=r"Copyright.*?(?:The\s+)?Associated Press",
                pattern_type="content",
                service_name="Associated Press",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="AP copyright statement",
            ),
            WireService(
                pattern=r"©.*?(?:The\s+)?NPR",
                pattern_type="content",
                service_name="NPR",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="NPR copyright",
            ),
            WireService(
                pattern=r"Copyright.*?WAVE",
                pattern_type="content",
                service_name="WAVE",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="WAVE copyright",
            ),
            WireService(
                pattern=r"\btold AFP\b",
                pattern_type="content",
                service_name="AFP",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="AFP attribution",
            ),
            WireService(
                pattern=r"first appeared in the Kansas Reflector",
                pattern_type="content",
                service_name="States Newsroom",
                case_sensitive=False,
                priority=15,
                active=True,
                notes="States Newsroom syndication",
            ),
        ]

        for pattern in patterns:
            session.add(pattern)

        session.commit()

    yield
