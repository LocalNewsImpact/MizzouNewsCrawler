"""Telemetry built its connection URL with `str(engine.url)`.

SQLAlchemy MASKS the password in `URL.__str__` -- it renders as `***` so
a URL in a log or a traceback carries no credential. That is right, and
it makes `str(engine.url)` the wrong way to hand a working connection
string to something that opens its own engine. Telemetry did exactly
that, so it built an engine whose password was three literal asterisks
and every connection came back `28P01 password authentication failed`.

WHY NOTHING CAUGHT IT. In production the pods reach Cloud SQL through
the connector and carry no password in the URL at all: masking has
nothing to mask, and the broken string is byte-identical to the working
one. It fails only where the corpus is reached by host and password --
the Cloud SQL Auth Proxy, a local Postgres, anything run from a laptop.
`backfill-verifications` could not open a connection on 2026-09-14 for
this reason and no other, and the traceback pointed at the corpus
database, which was answering `psql` on the same socket at the time.

The masked form is still correct where the string is an IDENTIFIER
rather than a credential -- `comprehensive_telemetry` passes the engine
itself and only names it. Both uses are asserted here, because the
difference between them is the whole bug.
"""

from __future__ import annotations

import ast
from pathlib import Path

from sqlalchemy.engine.url import make_url

from src.utils.telemetry import _url_with_its_password

TELEMETRY = Path(__file__).resolve().parent.parent / "src/utils/telemetry.py"


class TestTheRenderedUrlCanConnect:
    def test_the_password_survives(self):
        url = make_url("postgresql+pg8000://user:s3cret@127.0.0.1:5432/corpus")
        assert "s3cret" in _url_with_its_password(url)

    def test_str_is_what_would_not_have(self):
        """The bug, stated as the thing the fix replaced."""
        url = make_url("postgresql+pg8000://user:s3cret@127.0.0.1:5432/corpus")
        assert "s3cret" not in str(url)
        assert "***" in str(url)

    def test_it_round_trips_to_the_same_password(self):
        """A rendered URL has to parse back to what it came from --
        punctuation in a password is the ordinary case, and a rendering
        that loses it fails the same way the mask did."""
        raw = "p/a+s s=w0rd"
        url = make_url("postgresql+pg8000://user:x@127.0.0.1:5432/corpus").set(
            password=raw
        )
        assert make_url(_url_with_its_password(url)).password == raw

    def test_a_url_with_no_password_is_unchanged(self):
        """What production has: the Cloud SQL connector supplies the
        credential, so the URL carries none and both forms agree."""
        url = make_url("postgresql+pg8000://user@/corpus")
        assert _url_with_its_password(url) == str(url)


class TestNothingConnectsFromTheMaskedForm:
    """Asserted on the source: the failure is in which call was made, and
    reaching it at runtime needs a database that wants a password --
    which is precisely the environment that does not exist in CI."""

    def _function(self, name):
        tree = ast.parse(TELEMETRY.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == name:
                    return ast.unparse(node)
        raise AssertionError(f"{name} is gone from telemetry.py")

    def test_the_factory_renders_the_password(self):
        source = self._function("create_telemetry_system")
        assert "_url_with_its_password(db.engine.url)" in source
        assert "str(db.engine.url)" not in source

    def _method(self, class_name, method):
        tree = ast.parse(TELEMETRY.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for child in node.body:
                    if (
                        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == method
                    ):
                        return ast.unparse(child)
        raise AssertionError(f"{class_name}.{method} is gone")

    def test_the_tracker_renders_it_too(self):
        """Both build a URL the same way, and fixing only one leaves the
        bug reachable through the other -- the tracker can be constructed
        directly, without the factory."""
        source = self._method("OperationTracker", "__init__")
        assert "_url_with_its_password(db.engine.url)" in source
        assert "str(db.engine.url)" not in source

    def test_no_connecting_caller_is_left_anywhere_in_the_module(self):
        assert "str(db.engine.url)" not in TELEMETRY.read_text()

    def test_an_engine_handed_in_is_reused_not_rebuilt(self):
        """`_resolve_store` was given a live engine and threw it away to
        rebuild one from its masked URL. Passing it through fixes the
        credential and avoids a second pool onto the same database."""
        source = self._function("_resolve_store")
        assert "engine=candidate" in source


class TestTheIdentifierUseIsLeftMasked:
    def test_comprehensive_telemetry_still_masks(self):
        """It passes `engine=db.engine`, so nothing connects from the
        string -- and an unmasked URL there would put a credential into a
        store cache key for no gain."""
        source = Path("src/utils/comprehensive_telemetry.py").read_text()
        assert "database_url = str(db.engine.url)" in source
        assert "get_store(database_url, engine=db.engine)" in source
