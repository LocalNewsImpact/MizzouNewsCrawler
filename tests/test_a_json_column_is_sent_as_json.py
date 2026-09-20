"""A link's `meta` reaches PostgreSQL as json, not as a string.

`scripts/manual_enqueue_urls.py` sets `meta = {"manual_import": true}` on
every row and failed on the very first production run: pandas bound the
value as VARCHAR and PostgreSQL refused the json column. The error surfaced
three layers up as "in failed transaction block", and the dry run -- which
never inserts -- could not have caught it.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import JSON

from src.models import database


class _Engine:
    dialect = type("D", (), {"name": "postgresql"})()

    def raw_connection(self):
        raise RuntimeError("no raw connection in this test")

    def connect(self):
        raise RuntimeError("no introspection in this test")


def test_meta_is_typed_as_json(monkeypatch):
    seen = {}

    def fake_to_sql(self, name, con, **kwargs):
        seen.update(kwargs)
        return len(self)

    monkeypatch.setattr(pd.DataFrame, "to_sql", fake_to_sql)
    df = pd.DataFrame(
        [
            {
                "url": "https://x.example/a",
                "source": "x",
                "meta": '{"manual_import": true}',
            }
        ]
    )
    database.bulk_insert_candidate_links(_Engine(), df, if_exists="append")
    assert isinstance(seen.get("dtype", {}).get("meta"), JSON)


def test_no_meta_means_no_dtype(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        pd.DataFrame,
        "to_sql",
        lambda self, name, con, **kw: seen.update(kw) or len(self),
    )
    df = pd.DataFrame([{"url": "https://x.example/b", "source": "x"}])
    database.bulk_insert_candidate_links(_Engine(), df, if_exists="append")
    assert seen.get("dtype") is None
