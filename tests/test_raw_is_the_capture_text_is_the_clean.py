"""`raw` is the capture, `text` is the clean -- pinned on every statement.

The two columns held that meaning before this and nothing said so; the
model called the input column "core content" and the one every stage should
read "kept for compatibility". These tests make the names load-bearing: a
statement that reads or writes the wrong column fails here, not in
production three months later when the columns have diverged enough to
matter.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from src.cli.commands import cleaning, extraction, rot47_body_repair
from src.enrichment import repository, restore_points
from src.models import Article
from src.services.classification_service import ArticleClassificationService

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "b1c2d3e4f5a7_raw_is_the_capture_text_is_the_clean.py"
)


class TestTheModelSaysWhichIsWhich:
    def test_the_capture_is_called_raw(self):
        assert hasattr(Article, "raw")
        assert not hasattr(Article, "content"), "the misleading name is gone"

    def test_the_clean_body_keeps_its_name(self):
        assert hasattr(Article, "text")


class TestExtractionWritesBothAndNamesThemHonestly:
    def test_the_insert_writes_the_capture_to_raw(self):
        sql = str(extraction.ARTICLE_INSERT_SQL)
        assert "raw, text," in sql
        assert ":raw, :text," in sql
        assert "content" not in sql

    def test_the_refetch_replaces_the_capture_in_raw(self):
        sql = str(extraction.ARTICLE_REFETCH_SQL)
        assert "SET raw = :raw, text = :text" in sql
        assert "content" not in sql

    def test_the_batch_binds_the_capture_under_the_new_name(self):
        src = inspect.getsource(extraction._process_batch)
        assert '"raw": content_text' in src
        assert '"text": cleaned_text' in src
        assert '"content": content_text' not in src


class TestNothingDownstreamWritesTheCapture:
    def test_the_cleaning_pass_writes_only_the_clean_body(self):
        """This was the live defect: cleaning wrote cleaned prose back into
        the capture, so 159,709 of 165,609 rows had the two columns
        byte-identical and nothing could measure what cleaning removed."""
        sql = str(cleaning.ARTICLE_UPDATE_SQL)
        assert "SET text = :text" in sql
        assert "raw" not in sql
        assert "content" not in sql

    def test_extractions_own_update_leaves_the_capture_alone(self):
        assert "raw" not in str(extraction.ARTICLE_UPDATE_SQL)


class TestTheRepairReadsAndRewritesTheCapture:
    """ROT47 ciphertext is a property of the capture; decoding it is the one
    legitimate rewrite of `raw`, and it says so by name."""

    def test_it_finds_ciphertext_in_raw(self):
        assert "a.raw LIKE '%k^Am%'" in str(rot47_body_repair.FIND_SQL)

    def test_it_writes_the_decoded_capture_to_raw(self):
        sql = str(rot47_body_repair.REPAIR_SQL)
        assert "SET raw = :raw" in sql
        assert "content" not in sql


class TestEveryReaderNamesTheColumnItMeans:
    def test_cin_reads_the_clean_body_first_and_the_capture_last(self):
        assert ArticleClassificationService._BODY_FIELD_PREFERENCE == ("text", "raw")

    def test_enrichment_still_reads_the_capture_by_its_real_name(self):
        """Behaviour unchanged on purpose: the paywall thresholds were measured
        against this column, and moving enrichment to `text` re-measures
        them. That is its own change. Here the column is only named honestly."""
        for sql in (repository._CANDIDATE_SQL, repository._REPROCESS_SQL):
            body = str(sql)
            assert "a.raw" in body
            assert "coalesce(a.raw, '') <> ''" in body
            assert "content" not in body

    def test_restore_points_read_the_capture_then_the_clean(self):
        assert "COALESCE(a.raw, a.text, '')" in str(restore_points._CANDIDATES)


class TestTheMigrationSaysWhatItMeasures:
    def test_text_length_prefers_the_clean_body(self):
        migration = MIGRATION.read_text()
        assert (
            "NEW_EXPRESSION = \"length(coalesce(text, raw, text_excerpt, ''))\""
            in migration
        )
        assert "GENERATED ALWAYS AS" in migration and "STORED" in migration

    def test_the_downgrade_restores_the_old_expression_verbatim(self):
        migration = MIGRATION.read_text()
        assert (
            "OLD_EXPRESSION = \"length(coalesce(content, text, text_excerpt, ''))\""
            in migration
        )
        assert "RENAME COLUMN raw TO content" in migration

    def test_it_follows_the_current_head(self):
        assert 'down_revision = "z6f7a8b9c0d1"' in MIGRATION.read_text()


class TestNoStatementAnywhereNamesTheOldColumn:
    """The rename missed `orchestration/continuous_processor.py` because the
    sweep covered src/, scripts/, tests/ and backend/ and the processor image
    also copies orchestration/. Its 60-second cycle then failed on
    `column "content" does not exist` from the moment the migration ran.

    So the sweep is a test now, over every root an image copies, with the
    same column-shaped patterns. `article.content` is deliberately absent:
    that is `ArticleInput.content`, enrichment's internal dataclass field.
    """

    ROOTS = ("src", "orchestration", "backend", "scripts", "sitecustomize.py")
    COLUMN_SHAPED = re.compile(
        r"a\.content\b|articles\.content\b|\bSET content\b|:content\b"
        r"|\bcontent (IS|LIKE)\b|, content, text\b|content, text_hash"
        r"|\bArticle\.content\b|\brow\.content\b"
    )

    def test_every_root_an_image_copies_is_clean(self):
        repo = Path(__file__).resolve().parents[1]
        offenders = []
        for root in self.ROOTS:
            path = repo / root
            files = [path] if path.is_file() else path.rglob("*.py")
            for file in files:
                if "__pycache__" in file.parts:
                    continue
                for lineno, line in enumerate(
                    file.read_text(encoding="utf-8").splitlines(), 1
                ):
                    stripped = line.lstrip()
                    # Python and SQL comments may recount history by its old name.
                    if stripped.startswith(("#", "--")):
                        continue
                    if self.COLUMN_SHAPED.search(line):
                        offenders.append(
                            f"{file.relative_to(repo)}:{lineno}: {line.strip()[:80]}"
                        )
        assert not offenders, "\n".join(offenders)
