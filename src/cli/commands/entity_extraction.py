"""
Entity extraction command for backfilling entities on existing articles.

This command processes articles that have content but no entity data,
extracting location entities and storing them in the article_entities table.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import text as sql_text

from src.models.database import (
    DatabaseManager,
    safe_session_execute,
    save_article_entities,
)
from src.pipeline.entity_extraction import (
    ArticleEntityExtractor,
    attach_gazetteer_matches,
    attach_state_matches,
    get_gazetteer_rows,
    get_state_features,
)
from src.pipeline.statewide_gazetteer import scope_for

logger = logging.getLogger(__name__)


def log_and_print(message: str, level: str = "info") -> None:
    """Log message (logging already outputs to stdout in container environments).

    Note: The 'print' was removed to avoid duplicate log lines when run via
    continuous_processor.py which streams subprocess output to logs.
    """
    getattr(logger, level)(message)


def add_entity_extraction_parser(subparsers):
    """Add extract-entities command parser to CLI."""
    parser = subparsers.add_parser(
        "extract-entities",
        help="Extract entities from articles that have content but no entity data",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of articles to process per run (default: 100)",
    )
    parser.add_argument(
        "--source",
        type=str,
        help="Limit to a specific source name",
    )
    parser.add_argument(
        "--redo-before",
        default=None,
        help=(
            "With --redo-enriched: only articles last extracted before this "
            "ISO timestamp. A batched run must pass the SAME value to every "
            "invocation, or each one takes 'now' as its cutoff and reselects "
            "what the previous one just finished."
        ),
    )
    parser.add_argument(
        "--redo-enriched",
        action="store_true",
        help=(
            "Re-extract articles that already have entities, for the enriched "
            "corpus only. The spans are what changed: entities extracted under "
            "the per-source gazetteer are frozen at the spans spaCy chose then, "
            "and a rematch cannot reach inside them."
        ),
    )
    parser.set_defaults(func=handle_entity_extraction_command)


def handle_entity_extraction_command(args, extractor=None) -> int:
    """Execute entity extraction command logic.

    Processes articles that have content but no entries in article_entities table.

    Args:
        args: Command arguments containing limit and source filters
        extractor: Optional pre-loaded ArticleEntityExtractor instance. If None,
                   a new extractor will be created (loading the spaCy model).
    """
    limit = getattr(args, "limit", 100)
    source = getattr(args, "source", None)
    redo_enriched = getattr(args, "redo_enriched", False)
    # The cutoff belongs to the CAMPAIGN, not to one invocation. Taking
    # `now` per call means a batch finished a minute ago is still "before
    # now" on the next call, so the run reselects it and never advances.
    redo_before = getattr(args, "redo_before", None)
    redo_started_at = (
        datetime.fromisoformat(redo_before)
        if redo_before
        else datetime.now(timezone.utc)
    )

    # Log startup with visibility
    log_and_print("🚀 Starting entity extraction...")
    log_and_print(f"   Processing limit: {limit} articles")
    if source:
        log_and_print(f"   Source filter: {source}")
    log_and_print("")

    db = DatabaseManager()

    # Use provided extractor or create new one
    if extractor is None:
        log_and_print("🧠 Loading spaCy model...")
        extractor = ArticleEntityExtractor()
        log_and_print("✅ spaCy model loaded")

    try:
        with db.get_session() as session:
            # Query for articles with row-level locking for parallel processing
            #
            # Parallel Processing Strategy:
            # -----------------------------
            # - FOR UPDATE SKIP LOCKED locks all selected articles
            # - Articles processed source-by-source (for gazetteer efficiency)
            # - save_article_entities(autocommit=False) used per article
            # - Batch commit after each source releases locks together
            # - Other workers skip locked articles, grab different ones
            # - entities_extracted_at prevents re-processing on subsequent runs
            #
            # That column replaced `NOT EXISTS (SELECT 1 FROM article_entities
            # ...)`. The anti-join had to consider the whole corpus to find the
            # few articles still pending — 150k articles against 2.7M entity
            # rows to locate ~80 — so it grew more expensive the more work was
            # already done, and eventually exceeded the 120s statement_timeout
            # set on the role, failing every cycle. Matching on recorded state
            # makes the lookup proportional to work outstanding instead, via a
            # partial index that shrinks as the queue drains.
            #
            # ORDER BY is unchanged on purpose: articles are processed
            # source-by-source so each publisher's gazetteer is loaded once.
            query = sql_text(
                """
                SELECT a.id, a.text, a.text_hash, cl.source_id, cl.dataset_id, cl.source
                FROM articles a
                JOIN candidate_links cl ON a.candidate_link_id = cl.id
                -- Gate on `text`, which is the column this query SELECTs and
                -- entity extraction consumes. It used to also require
                -- `content IS NOT NULL`: a canonical-capture check standing in
                -- for "has a body", on a field this query never reads. That was
                -- silently exclusionary while the wall/furniture branches blanked
                -- content before insert -- rows with a perfectly good cleaned
                -- body were skipped because the raw capture had been emptied.
                WHERE a.text IS NOT NULL
                AND a.status NOT IN ('error', 'paywall', 'wire', 'not_article')
                """
                + (
                    # RE-EXTRACTION, not a wider net.
                    #
                    # Stored spans come from the extraction that produced
                    # them, and the per-source gazetteer chose different
                    # ones: "Liberal Arts Week Three Rivers College" where
                    # the statewide gazetteer holds "Three Rivers College".
                    # A rematch compares stored text and cannot reach
                    # inside a span, so those articles keep failing the
                    # gate however good the gazetteer gets.
                    #
                    # Scoped to the enriched corpus because that is what
                    # the grounding gate reads.
                    """
                AND EXISTS (SELECT 1 FROM article_enrichment e
                             WHERE e.article_id = a.id)
                -- Resumability. Without it the same LIMIT rows come back
                -- on every pass, a batched run reprocesses its first
                -- batch for ever, and a progress check reads that as
                -- "no progress" and stops. `entities_extracted_at` is
                -- stamped as each batch commits, so this shrinks as the
                -- run proceeds -- and a run interrupted halfway resumes
                -- where it stopped rather than starting again.
                AND (a.entities_extracted_at IS NULL
                     OR a.entities_extracted_at < :redo_before)
                """
                    if redo_enriched
                    else """
                AND a.entities_extracted_at IS NULL
                """
                )
                + ("AND cl.source = :source" if source else "")
                + """
                ORDER BY cl.source_id, cl.dataset_id
                LIMIT :limit
                FOR UPDATE OF a SKIP LOCKED
            """
            )

            params = {"limit": limit}
            if source:
                params["source"] = source
            if redo_enriched:
                # Set once when the command starts, so every batch of one
                # run shares a cutoff and articles this run has already
                # done fall out of the next batch.
                params["redo_before"] = redo_started_at

            result = safe_session_execute(session, query, params)
            rows = result.fetchall()

            if not rows:
                log_and_print("ℹ️  No articles found needing entity extraction")
                return 0

            log_and_print(f"📊 Found {len(rows)} articles needing entity extraction")

            # Group articles by source for efficient processing
            from collections import defaultdict

            articles_by_source = defaultdict(list)
            for row in rows:
                article_id, text, text_hash, source_id, dataset_id, source_name = row
                articles_by_source[(source_id, dataset_id)].append(
                    (article_id, text, text_hash, source_name)
                )

            num_sources = len(articles_by_source)
            log_and_print(f"   Grouped into {num_sources} source/dataset combos")
            log_and_print("")

            processed = 0
            errors = 0
            stop_logging = threading.Event()

            # Start timer-based progress logging
            start_time = time.time()

            def log_progress_periodically():
                """Log progress every 30 seconds regardless of article count."""
                while not stop_logging.is_set():
                    if stop_logging.wait(30):  # Wait 30s or until stop signal
                        break
                    elapsed = time.time() - start_time
                    msg = (
                        f"⏱️ Entity extraction: {processed}/{len(rows)} "
                        f"done ({elapsed:.1f}s)"
                    )
                    log_and_print(msg)

            # Start background progress logger
            progress_thread = threading.Thread(
                target=log_progress_periodically, daemon=True
            )
            progress_thread.start()

            log_and_print("🚀 Starting background progress logger (reports every 30s)")

            # Process articles source-by-source for efficient gazetteer reuse
            for (source_id, dataset_id), articles in articles_by_source.items():
                source_name = articles[0][3] if articles else "unknown"
                msg = f"📰 Processing {len(articles)} articles from {source_name}"
                log_and_print(msg)

                # THE STATEWIDE GAZETTEER, scoped to what this source
                # actually reaches (docs/STATEWIDE_GAZETTEER.md §9). A
                # Washington publisher never reads Missouri's, and a
                # source whose state could not be resolved -- the 901
                # national student papers -- reads nothing rather than
                # everything.
                states = scope_for(session, source_id)
                if states:
                    features = _features_for_states(session, tuple(states))
                    gazetteer_rows = features
                    ruler_key = "+".join(states)
                    log_and_print(
                        f"   {len(features)} features across {', '.join(states)}"
                    )
                else:
                    # No scope recorded. Fall back to the per-source
                    # build rather than skipping the article entirely:
                    # the statistical entities are still worth having,
                    # and the gate will not accept evidence from an
                    # unscoped source anyway.
                    gazetteer_rows = get_gazetteer_rows(session, source_id, dataset_id)
                    ruler_key = None
                    log_and_print(
                        f"   no state scope; {len(gazetteer_rows)} per-source entries"
                    )

                for article_id, text, text_hash, _ in articles:
                    try:
                        # Extract entities from article text
                        entities = extractor.extract(
                            text,
                            gazetteer_rows=gazetteer_rows,
                            cache_key=ruler_key,
                        )

                        # Exactly, and only within this source's states.
                        # The similarity threshold is gone: it matched
                        # "St. Louis City" to St. Louis COUNTY 206 times.
                        if states:
                            entities = attach_state_matches(entities, gazetteer_rows)
                        else:
                            entities = attach_gazetteer_matches(
                                session,
                                source_id,
                                dataset_id,
                                entities,
                                gazetteer_rows=gazetteer_rows,
                            )

                        # Save entities without committing (batch commit below)
                        save_article_entities(
                            session,
                            str(article_id),
                            entities,
                            extractor.extractor_version,
                            text_hash,
                            autocommit=False,
                        )

                        processed += 1

                    except Exception as exc:
                        error_msg = (
                            f"Failed to extract entities for article "
                            f"{article_id}: {exc}"
                        )
                        log_and_print(error_msg, level="error")
                        logger.exception(
                            "Failed to extract entities for article %s: %s",
                            article_id,
                            exc,
                        )
                        errors += 1
                        session.rollback()

                # Commit all entities for this source batch
                session.commit()

                # Manually run ANALYZE on article_entities to update query planner stats
                # This is necessary because we disabled autovacuum analyze for this
                # write-once, read-many table to avoid daily overhead
                from sqlalchemy import text

                session.execute(text("ANALYZE article_entities"))

                # Log progress after each source
                progress_msg = (
                    f"✓ Completed {source_name}: {processed}/{len(rows)} total"
                )
                log_and_print(progress_msg)

            # Stop background progress logger
            stop_logging.set()
            progress_thread.join(timeout=1)  # Wait up to 1s for thread to stop

            log_and_print("")
            log_and_print("✅ Entity extraction completed!")
            log_and_print(f"   Processed: {processed} articles")
            log_and_print(f"   Errors: {errors}")
            log_and_print("")

            return 0 if errors == 0 else 1

    except Exception as exc:
        error_msg = f"Entity extraction failed: {exc}"
        log_and_print(error_msg, level="error")
        logger.exception("Entity extraction failed: %s", exc)
        return 1


@lru_cache(maxsize=4)
def _features_cache_key(states: tuple[str, ...]):
    """Identity for a set of states; the rows themselves are fetched by
    `_features_for_states`, which caches on this."""
    return states


_FEATURES: dict[tuple[str, ...], list] = {}


def _features_for_states(session, states: tuple[str, ...]) -> list:
    """A state set's features, fetched once per run.

    Missouri is 32,327 features and Washington 49,650. Fetching them per
    source would be a full table read for every publisher in the state.
    """
    if states not in _FEATURES:
        if len(_FEATURES) >= 4:
            _FEATURES.pop(next(iter(_FEATURES)))
        _FEATURES[states] = get_state_features(session, list(states))
    return _FEATURES[states]
