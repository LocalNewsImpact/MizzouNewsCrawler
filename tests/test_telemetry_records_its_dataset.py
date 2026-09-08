"""Eight telemetry tables recorded what the pipeline did and never which
dataset it did it for.

`jobs` came closest, carrying a `dataset_label` inside its `params` JSON --
the label, not the key, and not a column anything can filter on. Everywhere
else the dataset was recoverable only by joining back to `candidate_links`,
which is the one table that holds it. Answering "what has extraction done
for Mizzou in the last hour" meant a text join across 315k rows to recover
a fact the writing job already had in hand.

The column holds the UUID. Three spellings of a dataset are already in
circulation -- the CLI accepts a name, a slug or a UUID; `params` stores the
label; the review UI shows the label -- and the database keys on the UUID
alone. Mixing them is not hypothetical: `extract-url` wrote its `--dataset`
slug directly into `candidate_links.dataset_id`, and the backfill selected
on `datasets.slug`. Both are corrected here, and both are covered below.
"""

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.utils.byline_telemetry import BylineCleaningTelemetry
from src.utils.comprehensive_telemetry import ComprehensiveExtractionTelemetry
from src.utils.telemetry import OperationTracker

DATASET = "61ccd4d3-763f-4cc6-b85d-74b268e80a00"


def test_extraction_telemetry_stamps_the_dataset_it_was_built_with():
    telemetry = ComprehensiveExtractionTelemetry(store=MagicMock(), dataset_id=DATASET)
    assert telemetry.dataset_id == DATASET


def test_extraction_telemetry_without_a_dataset_records_none_not_a_guess():
    """A run that was not scoped to a dataset must say so. Inferring one
    from the host is what this column exists to stop."""
    telemetry = ComprehensiveExtractionTelemetry(store=MagicMock())
    assert telemetry.dataset_id is None


def test_the_job_row_records_the_dataset_as_a_column():
    """Not only inside params, where it cannot be filtered on."""
    # Nothing connects: the store is mocked and the schema check patched.
    # Notably no sqlite URL stands in here -- this pipeline has no sqlite.
    with (
        patch.object(OperationTracker, "_resolve_store", return_value=MagicMock()),
        patch.object(OperationTracker, "_ensure_base_schema"),
    ):
        tracker = OperationTracker(database_url="postgresql://x", dataset_id=DATASET)

    assert tracker.dataset_id == DATASET

    source = inspect.getsource(tracker._update_job_record)
    assert "dataset_id" in source, "the jobs INSERT must name the column"
    assert (
        'kwargs.get("dataset_id") or self.dataset_id' in source
    ), "an explicit per-call dataset wins; the run's dataset is the default"


def test_byline_telemetry_carries_the_dataset():
    assert BylineCleaningTelemetry(dataset_id=DATASET).dataset_id == DATASET


def test_a_verification_decision_takes_its_dataset_from_the_link():
    """A verification run is not scoped to one dataset -- it sweeps every
    `discovered` link. The decision's dataset therefore has to come from the
    candidate link, which is authoritative per row, and not from the run."""
    from src.services.url_verification import URLVerificationService

    source = inspect.getsource(URLVerificationService.backfill_decisions)
    assert "dataset_id=row.dataset_id" in source


def test_the_backfill_selects_on_the_dataset_uuid_not_its_slug():
    from src.services.url_verification import URLVerificationService

    source = inspect.getsource(URLVerificationService.backfill_decisions)
    assert "d.id = :dataset" in source
    assert "d.slug = :dataset" not in source


def test_extract_url_resolves_its_dataset_before_writing_the_link():
    """`--dataset` is documented as a slug and `candidate_links.dataset_id`
    holds a UUID. Writing the slug makes the link invisible to every
    dataset-scoped query, the work queue included."""
    from src.cli.commands.extraction import handle_extract_url_command

    source = inspect.getsource(handle_extract_url_command)
    assert "resolve_dataset_id" in source
    assert "dataset_id=dataset_uuid" in source
    assert 'dataset_id=getattr(args, "dataset", None)' not in source


@pytest.mark.parametrize(
    "table",
    [
        "jobs",
        "verification_jobs",
        "extraction_telemetry_v2",
        "content_type_detection_telemetry",
        "url_verifications",
        "verification_telemetry",
        "byline_cleaning_telemetry",
        "article_enrichment",
    ],
)
def test_every_telemetry_table_gained_the_column(table):
    """The migration is the contract: a table that records what a run did
    records which dataset it did it for."""
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "r3s4t5u6v7w8_telemetry_records_its_dataset.py"
    ).read_text()

    assert f'("{table}"' in migration, f"{table} is not in the migration"


def test_extraction_telemetry_records_the_candidate_uuid():
    """`article_id` is minted before the extraction runs, so it names a row
    that may never be written: a paused source, a URL filtered as wire or
    weather, a 404. 156,712 of 315,631 production rows point at nothing.

    The candidate UUID exists for every discovered URL and is already in
    hand when telemetry starts -- the extraction loop passes the same value
    as `candidate_link_id` a few lines later -- so the row can name the
    thing it actually worked on."""
    from src.utils.comprehensive_telemetry import ExtractionMetrics

    metrics = ExtractionMetrics(
        "op-1",
        "article-uuid",
        "https://example.com/story",
        "Example",
        candidate_link_id="candidate-uuid",
    )

    assert metrics.candidate_link_id == "candidate-uuid"
    assert metrics.article_id == "article-uuid", "the pair, not a replacement"


def test_the_extraction_loop_passes_the_candidate_it_holds():
    """The value was already in the loop as `url_id`, used for
    `candidate_link_id=` on three writes below. It just never reached
    telemetry."""
    from src.cli.commands import extraction

    source = inspect.getsource(extraction)
    assert "candidate_link_id=str(url_id)" in source
    assert "candidate_link_id=str(candidate.id)" in source


def test_re_enriching_does_not_erase_the_dataset():
    """`article_enrichment` upserts on article_id, and 33 columns update on
    conflict. A dataset written by the first run has to survive a second
    one that was not given a dataset, or a reprocess quietly nulls it."""
    from src.enrichment import repository

    source = inspect.getsource(repository)
    assert (
        "dataset_id = COALESCE(EXCLUDED.dataset_id, article_enrichment.dataset_id)"
        in source
    )


def test_an_article_knows_how_long_it_is_without_being_read():
    """Every question about how much text an article holds was answered
    by reading the body. On a queue page that asks for every row of every
    count, that was the whole cost of the page: 254 seconds measured, 16.7
    of them in band chips that count rows BY length.

    A generated column: Postgres maintains it, so it cannot fall out of
    step with the four code paths that write `content` and `text`."""
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "s4t5u6v7w8x9_an_article_knows_how_long_it_is.py"
    ).read_text()

    assert "GENERATED ALWAYS AS" in migration
    assert "STORED" in migration, "virtual cannot be indexed"
    assert (
        "length(coalesce(content, text, text_excerpt, ''))" in migration
    ), "the same fallback order the queue always used"
    assert "ix_articles_text_length" in migration
