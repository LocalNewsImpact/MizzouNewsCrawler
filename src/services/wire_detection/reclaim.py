"""A wire check that never finished must not strand its article forever.

`wire_check_status` goes to `processing` before the call and to a verdict
after it. Nothing sets it back. So a worker that dies mid-call -- an
evicted pod, an OOM, a node drained under it -- leaves the flag set, and
the article is excluded from enrichment by a status that describes a run
which ended months ago.

MEASURED 2026-09-14: four articles at `processing`, attempted 2026-02-09,
02-18, 03-05 and 09-05, still set. The oldest had been stuck ten months.
They were found only because one of them happened to be holding an open
rework row that somebody chased.

`error` is the same failure with a different shape. It is written when
the lookup raises, and nothing retries it -- so a transient outage is
permanent. All 15 errors in the corpus fall in two windows, one December
evening and one March day: MediaCloud was down, our articles were fine,
and 15 of them left the pipeline for good.

BOTH GO BACK TO `pending`, which is where the wire checker looks. The
reclaim is bounded by an attempt count so an article that genuinely
cannot be checked stops rather than cycling: the count lives in
`wire_check_metadata`, because it is the checker's working state and not
a property of the article worth a column of its own.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

LOG = logging.getLogger(__name__)

#: How long a wire check may plausibly be in flight. Generous against the
#: real thing -- the rate limiter alone allows 30 seconds between calls at
#: the configured 2/minute -- because reclaiming a call that is still
#: running makes a duplicate request to somebody else's service, which is
#: the opposite of what this module is for.
STALE_AFTER = "1 hour"

#: How many times a check is reclaimed before it is left alone. An
#: article that fails every attempt is telling us something about the
#: article, and cycling it forever is its own kind of impoliteness.
MAX_RECLAIMS = 3


def reclaim_stranded(engine, *, limit: int = 500) -> dict[str, int]:
    """Put stranded wire checks back in the queue. Returns what moved.

    Two statuses, counted apart: they are the same symptom from different
    causes, and a run that reclaims 400 `error` rows is an outage while
    one that reclaims 400 `processing` rows is workers dying.
    """
    moved: dict[str, int] = {}
    for status in ("processing", "error"):
        with engine.begin() as conn:
            # The attempt count has to survive the reclaim, or the bound
            # is no bound: every pass would reset it to zero and an
            # article that cannot be checked would cycle forever.
            ids = conn.execute(
                text("""
                    SELECT id,
                           coalesce(
                             CAST(wire_check_metadata::json->>'reclaims' AS integer), 0
                           ) AS reclaims
                      FROM articles
                     WHERE wire_check_status = :status
                       AND (
                             wire_check_attempted_at IS NULL
                             OR wire_check_attempted_at
                                < now() - CAST(:stale AS interval)
                           )
                       AND coalesce(
                             CAST(wire_check_metadata::json->>'reclaims' AS integer), 0
                           ) < :max_reclaims
                     LIMIT :limit
                    """),
                {
                    "status": status,
                    "stale": STALE_AFTER,
                    "max_reclaims": MAX_RECLAIMS,
                    "limit": limit,
                },
            ).all()
            for row in ids:
                conn.execute(
                    text(
                        "UPDATE articles SET wire_check_status = 'pending', "
                        "wire_check_error = NULL, "
                        "wire_check_metadata = CAST(:meta AS json) WHERE id = :id"
                    ),
                    {
                        "id": row.id,
                        "meta": (
                            '{"reclaims": %d, "reclaimed_from": "%s"}'
                            % (row.reclaims + 1, status)
                        ),
                    },
                )
        moved[status] = len(ids)
        if ids:
            LOG.info("reclaimed %d wire checks stranded at %s", len(ids), status)
    return moved
