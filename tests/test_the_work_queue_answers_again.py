"""Every worker asking for work got a 500, and it looked like idleness.

`_get_available_domains` filtered with a bare parameter:

    AND (:dataset IS NULL OR cl.dataset_id = :dataset)

`:dataset IS NULL` gives Postgres nothing to infer a type from, and
pg8000 -- unlike psycopg2 -- sends no type with it. So the statement
failed to plan at all:

    42P18: could not determine data type of parameter $1

on EVERY call, whether or not a dataset was passed. `/work/request`
answered 500 to every worker, and extraction through the Argo pipeline
could not run. Nothing said so: the pipeline reported no work, the queue
reported healthy, and the only trace was a traceback in a pod nobody was
reading.

A mocked session cannot catch this. The error comes from the server
planning the statement, so the test has to reach a real Postgres --
which is the argument for #177 in one example.
"""

import pytest
from sqlalchemy import text

from src.services.work_queue import WorkQueueCoordinator

QUERY_OWNER = WorkQueueCoordinator._get_available_domains


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.parametrize("dataset", [None, "some-dataset-id"])
def test_the_domains_query_plans_on_postgres(cloud_sql_session, dataset):
    """Both branches of the filter, because the failure was in planning
    and happened whichever value was passed."""
    coordinator = WorkQueueCoordinator.__new__(WorkQueueCoordinator)
    domains = QUERY_OWNER(coordinator, cloud_sql_session, dataset)
    assert isinstance(domains, list)


@pytest.mark.postgres
@pytest.mark.integration
def test_the_shape_that_broke_it_is_driver_dependent(cloud_sql_session):
    """Why the fix avoids the construct rather than casting it.

    `:x IS NULL` fails under pg8000, which sends no type and leaves
    Postgres unable to infer one, and works under psycopg2, which does.
    Production uses pg8000; this suite may use either. So the assertion
    here is not that it raises -- that depends on the driver, and an
    earlier version of this test failed in integration for exactly that
    reason -- but that the form the fix uses works under both.
    """
    ok = cloud_sql_session.execute(
        text("SELECT 1 WHERE :x = :x OR :x IS NOT NULL"), {"x": "a"}
    ).scalar()
    assert ok == 1

    # And the shape the query actually uses now: one mention of the
    # parameter, and the clause absent when there is no value for it.
    scalar = cloud_sql_session.execute(
        text("SELECT 1 WHERE 'a' = :dataset"), {"dataset": "a"}
    ).scalar()
    assert scalar == 1


def test_the_query_casts_its_parameter():
    """Readable without a database, so a change to that line fails here
    even when the Postgres suite is not being run."""
    import inspect

    # SQL only. The comment above that line quotes the broken form to
    # explain it, so a naive substring check reads its own documentation.
    sql = "\n".join(
        line
        for line in inspect.getsource(QUERY_OWNER).splitlines()
        if not line.lstrip().startswith(("--", "#"))
    )
    assert "AND (:dataset IS NULL" not in sql, "Postgres cannot plan this"
    assert "cl.dataset_id = :dataset" in sql
    # Once only: SQLite turns each occurrence into its own positional
    # placeholder, so a repeated name stops matching its bindings.
    assert sql.count(":dataset") == 1
