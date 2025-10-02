import sys
from pathlib import Path

# Ensure repo root is importable when pytest runs from workspace
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import scripts.populate_gazetteer as populate_gazetteer
from scripts.populate_gazetteer import get_cached_geocode, set_cached_geocode
from src.models import Base, GeocodeCache


def setup_memory_db():
    # Use StaticPool and check_same_thread so the in-memory DB is shared
    # across connections used by create_all() and Session(). This avoids the
    # common SQLite in-memory isolation gotcha where each connection sees an
    # independent empty database.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_claim_and_set_ready():
    session = setup_memory_db()

    provider = "nominatim"
    inp = "1600 Pennsylvania Ave NW, Washington, DC"

    # Initially claim the row — should return an in_progress row
    row = get_cached_geocode(session, provider, inp, wait_timeout=0)
    assert row is not None
    assert getattr(row, "status", "") == "in_progress"

    # Now set the cached geocode to ready
    set_cached_geocode(
        session,
        provider,
        inp,
        lat=38.897663,
        lon=-77.036574,
        precision="address",
        raw_response={"mock": True},
        success=True,
        ttl_days=1,
    )

    # After setting, get_cached_geocode should return ready row
    ready = get_cached_geocode(session, provider, inp)
    assert ready is not None
    assert getattr(ready, "status", "") == "ready"
    assert abs((ready.lat or 0) - 38.897663) < 1e-6
    assert abs((ready.lon or 0) - -77.036574) < 1e-6


def test_get_cached_geocode_waits_for_ready(monkeypatch):
    session = setup_memory_db()

    provider = "nominatim"
    inp = "123 Main Street, Columbia, MO"
    norm = populate_gazetteer.normalize_geocode_key(inp)

    cache_row = GeocodeCache(
        provider=provider,
        input=inp,
        normalized_input=norm,
        status="in_progress",
        attempt_count=0,
    )
    session.add(cache_row)
    session.commit()

    sleep_calls: list[float] = []

    def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)
        session.execute(
            update(GeocodeCache)
            .where(
                GeocodeCache.provider == provider,
                GeocodeCache.normalized_input == norm,
            )
            .values(status="ready", lat=12.34, lon=-56.78)
        )
        session.commit()
        session.expire_all()

    monkeypatch.setattr(populate_gazetteer.time, "sleep", fake_sleep)

    row = get_cached_geocode(session, provider, inp, wait_timeout=5)

    assert row is not None
    assert getattr(row, "status", "") == "ready"
    assert abs((row.lat or 0) - 12.34) < 1e-6
    assert abs((row.lon or 0) - -56.78) < 1e-6
    assert sleep_calls == [0.5]


def test_get_cached_geocode_times_out(monkeypatch):
    session = setup_memory_db()

    provider = "nominatim"
    inp = "456 Elm Street, Boone County, MO"
    norm = populate_gazetteer.normalize_geocode_key(inp)

    cache_row = GeocodeCache(
        provider=provider,
        input=inp,
        normalized_input=norm,
        status="in_progress",
        attempt_count=0,
    )
    session.add(cache_row)
    session.commit()

    sleep_calls: list[float] = []

    def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    monkeypatch.setattr(populate_gazetteer.time, "sleep", fake_sleep)

    row = get_cached_geocode(session, provider, inp, wait_timeout=1)

    assert row is not None
    assert getattr(row, "status", "") == "in_progress"
    assert sleep_calls == [0.5, 1.0]
