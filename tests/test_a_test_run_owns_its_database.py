"""Each test session gets its own SQLite database, in its own directory.

The name used to be fixed -- `<tmp>/test_news_crawler.db` -- so every
checkout and every run on the machine shared one file. A copy left
unwritable by an earlier run made the next run fail during COLLECTION:

    sqlite3.OperationalError: attempt to write a readonly database
    ERROR collecting tests/integration/test_work_queue_integration.py

That file was neither the cause nor selected. It failed because
`src/services/work_queue.py` built a coordinator at import and touched
the database, so whichever module imported it first wore the error --
which is fixed in tests/test_importing_a_service_touches_no_database.py.
The pre-push hook rejected three pushes before the leftover was found.

Cleanup swallowed every error and only ran when a session ended
normally, which is how leftovers were made in the first place.
"""

import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

LEGACY = Path(tempfile.gettempdir()) / "test_news_crawler.db"

#: What conftest names the directory it makes.
PREFIX = "news-crawler-tests-"


def _database_file():
    """The database this session is actually using.

    Read from the environment rather than by importing conftest:
    `tests/` is not a package here, so pytest loads conftest as a
    top-level module and `import tests.conftest` executes a SECOND copy
    -- which makes its own directory, and the test then compares two
    different sessions. It failed exactly that way when written.
    """
    return Path(urlparse(os.environ["DATABASE_URL"]).path)


def test_the_session_database_is_not_the_shared_name():
    """The exact file that caused it."""
    assert _database_file() != LEGACY


def test_the_session_database_has_a_directory_of_its_own():
    """Its own directory, so SQLite's -wal and -shm cannot outlive it
    either."""
    parent = _database_file().parent
    assert parent.name.startswith(PREFIX), parent
    assert parent != Path(tempfile.gettempdir())


def test_that_directory_is_writable():
    """The failure was a database that could not be written, reported
    somewhere else entirely."""
    probe = _database_file().parent / "probe"
    probe.write_text("x")
    assert probe.read_text() == "x"
    probe.unlink()


def test_a_leftover_at_the_old_path_cannot_affect_a_run():
    """A read-only file at the old shared path is what broke three
    pushes. Nothing reads that path now, so it cannot."""
    assert LEGACY != _database_file()
    assert str(LEGACY) not in os.environ["DATABASE_URL"]


def test_a_database_this_suite_did_not_make_is_left_alone():
    """CI announces Postgres through DATABASE_URL, and a developer may
    point the suite at their own. Neither is this suite's to create or
    delete, and the directory it would remove is only ever one it made.
    """
    url = os.environ["DATABASE_URL"]
    if not url.startswith("sqlite:"):
        # Someone else's database: no directory of ours is involved.
        assert PREFIX not in url
    else:
        assert PREFIX in url
