"""Test PostgreSQL aggregate type handling.

This test validates that aggregate queries (COUNT, SUM, AVG, etc.) return
proper types and that our type conversion helpers work correctly with PostgreSQL.

PostgreSQL's pg8000 driver returns aggregate results as strings, while SQLite
returns native Python types. This test ensures our code handles both correctly.
"""

import pytest
from sqlalchemy import text

from src.cli.commands.extraction import _to_int as extraction_to_int
from src.cli.commands.pipeline_status import _to_int as pipeline_to_int


@pytest.mark.integration
@pytest.mark.postgres
class TestPostgreSQLAggregateTypes:
    """Test that aggregate queries work correctly with PostgreSQL."""

    def test_to_int_helper_with_string(self):
        """Test _to_int helper converts string to int."""
        assert pipeline_to_int("42", 0) == 42
        assert pipeline_to_int("0", 0) == 0
        assert pipeline_to_int("123", 0) == 123

    def test_to_int_helper_with_int(self):
        """Test _to_int helper passes through int."""
        assert pipeline_to_int(42, 0) == 42
        assert pipeline_to_int(0, 0) == 0
        assert pipeline_to_int(123, 0) == 123

    def test_to_int_helper_with_none(self):
        """Test _to_int helper returns default for None."""
        assert pipeline_to_int(None, 0) == 0
        assert pipeline_to_int(None, 99) == 99

    def test_to_int_helper_with_invalid(self):
        """Test _to_int helper returns default for invalid input."""
        assert pipeline_to_int("invalid", 0) == 0
        assert pipeline_to_int("", 0) == 0
        assert pipeline_to_int([], 0) == 0

    def test_extraction_to_int_helper(self):
        """Test extraction.py has compatible _to_int helper."""
        assert extraction_to_int("42", 0) == 42
        assert extraction_to_int(None, 0) == 0
        assert extraction_to_int("invalid", 0) == 0

    def test_count_query_returns_convertible_type(self, cloud_sql_session):
        """Test COUNT(*) query returns a type that _to_int can handle."""
        # Create a test table
        cloud_sql_session.execute(
            text(
                """
                CREATE TEMPORARY TABLE test_counts (
                    id SERIAL PRIMARY KEY,
                    value TEXT
                )
                """
            )
        )

        # Insert some test data
        for i in range(5):
            cloud_sql_session.execute(
                text("INSERT INTO test_counts (value) VALUES (:val)"),
                {"val": f"item_{i}"},
            )
        cloud_sql_session.commit()

        # Query count
        result = cloud_sql_session.execute(text("SELECT COUNT(*) FROM test_counts"))
        count_value = result.scalar()

        # The value should be convertible to int
        count_int = pipeline_to_int(count_value, 0)
        assert count_int == 5
        assert isinstance(count_int, int)

    def test_sum_query_returns_convertible_type(self, cloud_sql_session):
        """Test SUM() query returns a type that _to_int can handle."""
        # Create a test table with numeric values
        cloud_sql_session.execute(
            text(
                """
                CREATE TEMPORARY TABLE test_sums (
                    id SERIAL PRIMARY KEY,
                    amount INTEGER
                )
                """
            )
        )

        # Insert test data
        for i in range(1, 6):  # 1, 2, 3, 4, 5
            cloud_sql_session.execute(
                text("INSERT INTO test_sums (amount) VALUES (:amt)"),
                {"amt": i},
            )
        cloud_sql_session.commit()

        # Query sum
        result = cloud_sql_session.execute(text("SELECT SUM(amount) FROM test_sums"))
        sum_value = result.scalar()

        # The value should be convertible to int
        sum_int = pipeline_to_int(sum_value, 0)
        assert sum_int == 15  # 1+2+3+4+5
        assert isinstance(sum_int, int)

    def test_max_query_returns_convertible_type(self, cloud_sql_session):
        """Test MAX() query returns a type that _to_int can handle."""
        cloud_sql_session.execute(
            text(
                """
                CREATE TEMPORARY TABLE test_max (
                    id SERIAL PRIMARY KEY,
                    score INTEGER
                )
                """
            )
        )

        # Insert test data
        for score in [10, 25, 15, 30, 20]:
            cloud_sql_session.execute(
                text("INSERT INTO test_max (score) VALUES (:score)"),
                {"score": score},
            )
        cloud_sql_session.commit()

        # Query max
        result = cloud_sql_session.execute(text("SELECT MAX(score) FROM test_max"))
        max_value = result.scalar()

        # The value should be convertible to int
        max_int = pipeline_to_int(max_value, 0)
        assert max_int == 30
        assert isinstance(max_int, int)

    def test_aggregate_with_no_rows(self, cloud_sql_session):
        """Test COUNT(*) on empty table returns 0 correctly."""
        cloud_sql_session.execute(
            text(
                """
                CREATE TEMPORARY TABLE test_empty (
                    id SERIAL PRIMARY KEY
                )
                """
            )
        )
        cloud_sql_session.commit()

        # Query count on empty table
        result = cloud_sql_session.execute(text("SELECT COUNT(*) FROM test_empty"))
        count_value = result.scalar()

        # Should convert to 0
        count_int = pipeline_to_int(count_value, 999)
        assert count_int == 0

    def test_aggregate_with_null_result(self, cloud_sql_session):
        """Test SUM() with no rows returns NULL, converted to default."""
        cloud_sql_session.execute(
            text(
                """
                CREATE TEMPORARY TABLE test_null (
                    id SERIAL PRIMARY KEY,
                    amount INTEGER
                )
                """
            )
        )
        cloud_sql_session.commit()

        # Query sum on empty table (returns NULL)
        result = cloud_sql_session.execute(text("SELECT SUM(amount) FROM test_null"))
        sum_value = result.scalar()

        # NULL should convert to default
        sum_int = pipeline_to_int(sum_value, 0)
        assert sum_int == 0

    def test_scalar_or_pattern_fails_with_string(self):
        """Demonstrate that `.scalar() or 0` pattern fails with string results.

        This test documents the bug that existed before our fixes.
        PostgreSQL returns "0" as a string, which is truthy, so `"0" or 0`
        evaluates to "0" instead of 0.
        """
        # Simulate what PostgreSQL returns
        pg_result = "0"  # String, not int

        # The old pattern fails
        old_pattern_result = pg_result or 0
        assert old_pattern_result == "0"  # WRONG! We wanted 0
        assert old_pattern_result != 0  # This comparison would fail

        # The new pattern works
        new_pattern_result = pipeline_to_int(pg_result, 0)
        assert new_pattern_result == 0  # CORRECT!
        assert isinstance(new_pattern_result, int)

    def test_row_tuple_indexing_with_aggregates(self, cloud_sql_session):
        """Test that row[1] with COUNT aggregate needs int conversion."""
        cloud_sql_session.execute(
            text(
                """
                CREATE TEMPORARY TABLE test_groups (
                    id SERIAL PRIMARY KEY,
                    category TEXT,
                    value INTEGER
                )
                """
            )
        )

        # Insert test data
        for cat in ["A", "B", "C"]:
            for i in range(3):
                cloud_sql_session.execute(
                    text("INSERT INTO test_groups (category, value) VALUES (:cat, :val)"),
                    {"cat": cat, "val": i},
                )
        cloud_sql_session.commit()

        # Query with GROUP BY
        result = cloud_sql_session.execute(
            text(
                """
                SELECT category, COUNT(*) as count
                FROM test_groups
                GROUP BY category
                ORDER BY category
                """
            )
        )

        rows = result.fetchall()
        assert len(rows) == 3

        # Check that row[1] (the count) needs conversion
        for row in rows:
            category = row[0]
            count_raw = row[1]

            # Convert to int for safety
            count = pipeline_to_int(count_raw, 0)
            assert count == 3
            assert isinstance(count, int)

            # Can also use named access if available
            assert category in ["A", "B", "C"]
