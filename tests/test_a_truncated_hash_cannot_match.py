"""A content hash has one length, or it joins to nothing.

`calculate_content_hash` returns a full 64-character sha256 and every row the
crawler writes carries that. Two import scripts computed their own and cut it to
32 characters, so 1,041 articles held a value that cannot equal any
crawler-written hash however identical the text.

Duplicate detection between an imported body and a fetched one was therefore
impossible for those rows. A Port Townsend Leader search page stored under two
URLs was found by eye rather than by the hash, because the pair matched each
other -- both truncated the same way -- and nothing else in the corpus.

NOT IN tests/scripts/: tests/conftest.py marks everything there `local_scripts`
and pytest.ini deselects it, so a test placed there gates nothing.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BODY = "The Jackson County Environmental Health Division inspects restaurants."


class TestTheHashIsWholeEverywhere:
    def test_the_corpus_function_is_a_full_sha256(self):
        from src.models.database import calculate_content_hash

        assert (
            calculate_content_hash(BODY)
            == hashlib.sha256(BODY.encode("utf-8")).hexdigest()
        )
        assert len(calculate_content_hash(BODY)) == 64

    def test_the_wsu_import_uses_it(self):
        """Its own truncation is what made 451 of those rows unjoinable."""
        from src.models.database import calculate_content_hash

        mod = _script("import_wsu_notebook_labels")
        assert mod.text_hash(BODY) == calculate_content_hash(BODY)

    def test_the_manual_article_import_agrees(self):
        from src.models.database import calculate_content_hash

        mod = _script("import_manual_articles")
        assert mod.compute_text_hash(BODY) == calculate_content_hash(BODY)

    def test_no_import_script_truncates_a_content_hash(self):
        """The url_hash used to build an id may be short -- it is an id, not a
        join key. A content hash may not."""
        for name in ("import_wsu_notebook_labels", "import_manual_articles"):
            src = (ROOT / f"scripts/{name}.py").read_text()
            for line in src.splitlines():
                if "hexdigest()[:" in line and "url" not in line.lower():
                    raise AssertionError(f"{name} truncates a content hash: {line!r}")


class TestTheBackfill:
    def test_it_selects_only_short_hashes_with_a_body(self):
        """A hash of nothing is not a useful key, so an empty body is left
        alone rather than given the hash of the empty string."""
        mod = _script("backfill_truncated_text_hashes")
        sql = str(mod.FIND_SQL)
        assert "length(text_hash) < :full" in sql
        assert "coalesce(text, '') <> ''" in sql
        assert mod.FULL_HASH_CHARS == 64

    def test_it_recomputes_from_text_so_it_needs_no_source_data(self):
        mod = _script("backfill_truncated_text_hashes")
        assert "UPDATE articles SET text_hash" in str(mod.UPDATE_SQL)
