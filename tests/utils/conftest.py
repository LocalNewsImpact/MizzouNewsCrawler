"""Fixtures for utils tests."""

import pytest


@pytest.fixture(scope="function", autouse=True)
def populate_wire_service_patterns():
    """Populate wire_services table with test patterns.

    Uses the SQLite in-memory database that's configured in tests/conftest.py.
    Each test gets a fresh set of patterns.
    """
    from src.models import WireService, Base
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
