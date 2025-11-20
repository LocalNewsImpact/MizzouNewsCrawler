import logging
import threading

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.models import Base, CandidateLink
from src.models.database import DatabaseManager


class TestDBRaceConditions:
    """Tests for database race conditions."""

    @pytest.fixture
    def db_manager(self, tmp_path):
        """Create a DatabaseManager with a file-based SQLite DB for concurrency."""
        # In-memory SQLite doesn't work well with multiple threads sharing connections
        # So we use a file-based one.
        db_path = tmp_path / "race_test.db"
        db_url = f"sqlite:///{db_path}"

        manager = DatabaseManager(database_url=db_url)
        Base.metadata.create_all(manager.engine)
        return manager

    def test_concurrent_candidate_link_insertion(self, db_manager, caplog):
        """
        Test that concurrent insertions of the same URL result in IntegrityError
        and that the application can handle it (e.g. by ignoring duplicates).
        """
        caplog.set_level(logging.DEBUG)

        url = "http://example.com/race-condition"
        source = "test-source"

        results = []

        def insert_link():
            session = sessionmaker(bind=db_manager.engine)()
            try:
                link = CandidateLink(url=url, source=source)
                session.add(link)
                session.commit()
                results.append("success")
            except IntegrityError:
                session.rollback()
                results.append("integrity_error")
            except Exception as e:
                session.rollback()
                results.append(f"error: {e}")
            finally:
                session.close()

        # Create two threads trying to insert the same link
        t1 = threading.Thread(target=insert_link)
        t2 = threading.Thread(target=insert_link)

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        # One should succeed, one should fail with IntegrityError
        assert "success" in results
        assert "integrity_error" in results
        assert len(results) == 2

    def test_transaction_rollback_on_error(self, db_manager):
        """
        Test that a failed transaction is rolled back and doesn't leave the
        session in a bad state.
        """
        session = sessionmaker(bind=db_manager.engine)()

        # 1. Successful insert
        link1 = CandidateLink(url="http://example.com/1", source="test")
        session.add(link1)
        session.commit()

        # 2. Failed insert (duplicate)
        link2 = CandidateLink(url="http://example.com/1", source="test")
        session.add(link2)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()

        # 3. Verify session is usable for next insert
        link3 = CandidateLink(url="http://example.com/2", source="test")
        session.add(link3)
        session.commit()

        # Verify data
        count = session.query(CandidateLink).count()
        assert count == 2
        session.close()
