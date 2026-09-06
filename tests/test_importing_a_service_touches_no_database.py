"""Importing the work queue must not connect to anything.

`src/services/work_queue.py` ended with

    coordinator = WorkQueueCoordinator()

at module scope, so importing it built a DatabaseManager, which runs
`Base.metadata.create_all` (src/models/database.py). Every importer paid
for that -- including pytest, which imports a module merely to collect
the tests inside it.

It also sent failures to the wrong address. A stale, unwritable SQLite
file in the temp directory surfaced as

    ERROR collecting tests/integration/test_work_queue_integration.py
    sqlite3.OperationalError: attempt to write a readonly database

against a test that was deselected and never ran. It was the first
module to import this one, so it wore an error it had no part in, and
three pushes were investigated as a work-queue problem that did not
exist.

The database is named here as somewhere that cannot be written. Import
must not care; asking for the coordinator must.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: A database that cannot be opened: the directory does not exist and
#: cannot be created. Anything that connects will fail loudly.
UNREACHABLE = "sqlite:////nonexistent-directory-for-this-test/db.sqlite"


def _run(body: str):
    """Run a snippet in a fresh interpreter, with the unreachable database.

    A subprocess because import side effects happen once per process:
    inside this session the module is already imported, and the question
    is what a fresh import does.
    """
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(Path.home()),
            "DATABASE_URL": UNREACHABLE,
            "USE_CLOUD_SQL_CONNECTOR": "false",
            "PYTHONPATH": str(REPO),
        },
    )


def test_importing_the_module_does_not_connect():
    done = _run("""
        import src.services.work_queue as wq
        assert wq.app is not None
        assert wq._coordinator is None, "a coordinator was built at import"
        print("imported")
        """)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "imported" in done.stdout


def test_the_coordinator_is_built_on_demand_and_only_once():
    """The other half: the work still happens, just later.

    Without this a module that had simply deleted the coordinator would
    pass the test above. The assertion is the lazy singleton, not a
    connection: a SQLAlchemy engine connects on first use rather than on
    construction, and `create_all` runs only under the test-environment
    flag, so building a coordinator need not open anything -- which is
    what this test asserted at first, and was wrong about.
    """
    done = _run("""
        import src.services.work_queue as wq
        assert wq._coordinator is None
        first = wq.get_coordinator()
        assert wq._coordinator is first, "not remembered"
        assert wq.get_coordinator() is first, "built twice"
        print("built once, on demand")
        """)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "built once, on demand" in done.stdout


@pytest.mark.parametrize(
    "module",
    ["src.services.work_queue", "src.services.url_verification"],
)
def test_a_service_module_imports_without_a_database(module):
    """The rule, not the instance. A service that connects at import
    makes every importer a suspect."""
    done = _run(f"""
        import importlib
        importlib.import_module("{module}")
        print("ok")
        """)
    assert done.returncode == 0, done.stdout + done.stderr
