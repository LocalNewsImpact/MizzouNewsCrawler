"""The processor's pending-entities count asks what the worker asks.

`src/cli/commands/entity_extraction.py` records that `entities_extracted_at`
replaced `NOT EXISTS (SELECT 1 FROM article_entities ...)`, because the
anti-join considers the whole corpus to find the few articles still pending and
so grows more expensive the more work is already done. The processor's COUNT
kept the old form, and the two answers diverged the moment entity rows were
deleted without clearing the column: on 2026-09-19 the language backfill
removed 51,429 entity rows, and all 127 of those articles read as "pending"
forever while `entities_extracted_at` said done.

Measured against production: old 946ms returning 127, new 194ms returning 1 --
and the 127 made the processor invoke entity extraction every 60 seconds for
work that did not exist, which is how its companion select became the most
expensive statement in the database (18,766 calls, 15.8s mean, 297,363s).
"""

from __future__ import annotations

import re
from pathlib import Path

PROCESSOR = (
    Path(__file__).resolve().parents[1] / "orchestration" / "continuous_processor.py"
)
WORKER = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "cli"
    / "commands"
    / "entity_extraction.py"
)


def _count_block() -> str:
    """The SQL the processor actually sends, comments stripped.

    The comment above that query explains the old form by name, so a naive
    substring check would find `NOT EXISTS` in the explanation and pass while
    the query still used it.
    """
    source = PROCESSOR.read_text()
    start = source.index("Count articles without entity extraction")
    block = source[start : source.index('counts["entity_extraction_pending"]', start)]
    return "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("#")
    )


class TestTheCountMatchesTheWorker:
    def test_it_gates_on_the_recorded_state(self):
        assert "entities_extracted_at IS NULL" in _count_block()

    def test_the_anti_join_is_gone(self):
        """The form that grew more expensive as the queue drained."""
        block = _count_block()
        assert "NOT EXISTS" not in block
        assert "article_entities" not in block

    def test_it_does_not_gate_on_the_raw_capture(self):
        """The wall and furniture branches blank `raw` before insert, so an
        article with a perfectly good cleaned body counted as done while the
        worker still owed it."""
        assert "raw IS NOT NULL" not in _count_block()

    def test_it_reads_the_same_body_column_the_worker_reads(self):
        assert "text IS NOT NULL" in _count_block()

    def test_it_excludes_the_same_statuses_the_worker_excludes(self):
        block = _count_block()
        worker = WORKER.read_text()
        wanted = re.search(r"status NOT IN\s*\(?\s*'?\(?([^)]*error[^)]*)\)", worker)
        assert wanted, "the worker's excluded statuses moved"
        for status in ("error", "paywall", "wire", "not_article"):
            assert (
                status in block
            ), f"{status} is excluded by the worker, not by the count"


class TestTheWorkerIsStillTheAuthority:
    def test_the_worker_gates_on_the_column_not_the_anti_join(self):
        worker = WORKER.read_text()
        query_start = worker.index("SELECT a.id, a.text, a.text_hash")
        query = worker[query_start : query_start + 1200]
        assert "NOT EXISTS" not in query
