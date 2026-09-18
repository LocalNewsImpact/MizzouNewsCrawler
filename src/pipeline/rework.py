"""Which records a housekeeping run may touch.

THE SET IS THE DIFFERENCE. A housekeeping run is not a different kind of
extraction, classification or enrichment: it is the same stages, the same
parallel workers and the same work queue, with a narrower set of records
going in. This module is that set, in one place, because every stage needs
the same answer and a copy per stage is a copy that drifts.

A record is in the set when BOTH are true:

  it is flagged      -- `pipeline_rework` still owes work on it, which is
                        what a review decision wrote when it rewound the
                        record; and
  it is ready        -- it holds a status the stage reads.

Neither alone will do. The status is shared with the whole backlog (4,802
links sit at `article`, 450 articles at `cleaned`, 85,000 at `labeled`),
so a stage told only the status takes everything. The flag says nothing
about where the record has got to, so a stage told only the flag would
take a record that is not ready for it.

Joined, the workflow carries a record forward by itself. A flagged link is
fetched; the article it produces inherits the flag through the link; the
classify step reads `cleaned` and picks it up in the same run; enrichment
reads `labeled` and does the same. No stage has to write a row for the
next one, which is what the first version did -- and it fired on the
article's status before cleaning had run, so production logged "27 fetches
settled, 0 articles queued for classification" and four fresh articles sat
at `labeled` with nothing asking for their enrichment.

A row closes when its record is no longer in ANY status a stage reads:
in the export, retracted, or a kind no enrichment stage selects. Settled
on the status and never on having been attempted, so a stage that fails
leaves the work owed and tomorrow's run finds it.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: A link is ready to fetch when it is at this status and has no article.
#: Both conditions are extraction's own: its batch query reads
#: `candidate_links.status = 'article'` and excludes links that already
#: have an article, so a row for one of those would never close.
FETCHABLE = "article"

#: How many runs may take a rework row before it is given up on.
#:
#: Four links sat open from 2026-09-14, three on newspressnow.com and one on
#: fultonsun.com, where Selenium fails every time -- the extraction log reached
#: failure #136. The queue served them, every one failed, their domains entered
#: cooldown, and the step then waited 30 seconds and asked again for two hours
#: until the pod deadline killed the workflow. Both of the last two housekeeping
#: runs died that way without reaching classify or enrich.
#:
#: The bound belongs on the row, not in the run: the run that gives up is never
#: the run that tried before it, so three runs of infinite patience look exactly
#: like one. `reclaim.MAX_RECLAIMS` bounds the wire check the same way.
MAX_ATTEMPTS = 3

#: The outcome written when the bound is reached. The same word enrichment's
#: orchestrator uses for the same judgement, so "why did this stop" has one
#: answer across stages.
ABANDONED = "failed_max_attempts"


def _stage_statuses(record_type: str) -> list[str]:
    """Every status a housekeeping stage reads for this kind of record.

    From the shared contract rather than restated here: the pairing of
    stage to status is what the console and the crawler agree on, and a
    copy on either side is how they come to disagree.
    """
    from lnic_contracts import pipeline_rework as contract

    return sorted(
        {
            status
            for stage in contract.STAGES
            if contract.record_type_for(stage) == record_type
            for status in contract.selects(stage)
        }
    )


def links_to_fetch(session) -> list[str]:
    """Flagged links that are ready to be fetched, and nothing else.

    A row at `MAX_ATTEMPTS` is excluded. Without that the same unfetchable link
    is served on every run for ever, and the run cannot tell a link nobody has
    tried from one that has failed a hundred times.
    """
    rows = session.execute(
        text(
            "SELECT DISTINCT cl.id FROM pipeline_rework r "
            "JOIN candidate_links cl ON cl.id = r.record_id "
            "WHERE r.record_type = 'candidate_link' AND r.done_at IS NULL "
            "AND cl.status = :fetchable "
            "AND coalesce(r.attempts, 0) < :max_attempts "
            "AND NOT EXISTS (SELECT 1 FROM articles a "
            "                WHERE a.candidate_link_id = cl.id)"
        ),
        {"fetchable": FETCHABLE, "max_attempts": MAX_ATTEMPTS},
    ).fetchall()
    return [r[0] for r in rows]


def count_attempt(session, record_ids: list[str]) -> set[str]:
    """Spend an attempt on these records; return the ones now given up on.

    Called at the START of a step, matching `settle`: a row closed by a run's
    own attempt reads as closed on the next run rather than mid-flight.

    The ids come back rather than a count so the caller can drop them from the
    set it already holds. Re-reading `links_to_fetch` would be the obvious
    alternative and is wrong: the direct path reuses the set the guard read, and
    asking twice is a second query for an answer already in hand.

    The count is per ROW, not per stage, because what is being bounded is how
    many times anybody has tried this record -- a link that cannot be fetched
    does not become fetchable because a different stage asked.
    """
    if not record_ids:
        return set()
    session.execute(
        text(
            "UPDATE pipeline_rework SET attempts = coalesce(attempts, 0) + 1 "
            "WHERE done_at IS NULL AND record_id = ANY(:ids)"
        ),
        {"ids": list(record_ids)},
    )
    spent = session.execute(
        text(
            "UPDATE pipeline_rework SET done_at = now(), outcome = :outcome "
            "WHERE done_at IS NULL AND record_id = ANY(:ids) "
            "AND coalesce(attempts, 0) >= :max_attempts "
            "RETURNING record_id"
        ),
        {"ids": list(record_ids), "outcome": ABANDONED, "max_attempts": MAX_ATTEMPTS},
    )
    abandoned = {row[0] for row in (spent.fetchall() if spent is not None else [])}
    session.commit()
    if abandoned:
        logger.info(
            "rework: gave up on %d record(s) after %d attempts",
            len(abandoned),
            MAX_ATTEMPTS,
        )
    return abandoned


def articles_in(session, statuses) -> list[str]:
    """Flagged articles holding one of `statuses`.

    Flagged by their own row OR by the row on the link in front of them:
    when a decision rewound a URL there was no article to name, and the
    article the fetch produces is the record the remaining stages act on.
    That inheritance is what lets one run carry a record from fetch to
    enrichment without any stage writing a row.
    """
    wanted = list(statuses)
    if not wanted:
        return []
    rows = session.execute(
        text(
            "SELECT DISTINCT a.id FROM articles a "
            "WHERE a.status = ANY(:statuses) AND EXISTS ("
            "  SELECT 1 FROM pipeline_rework r WHERE r.done_at IS NULL AND ("
            "    (r.record_type = 'article' AND r.record_id = a.id)"
            "    OR (r.record_type = 'candidate_link' "
            "        AND r.record_id = a.candidate_link_id)"
            "  )"
            ")"
        ),
        {"statuses": wanted},
    ).fetchall()
    return [r[0] for r in rows]


def settle(session) -> int:
    """Close the rows of records that have nothing left owing.

    A record is finished with housekeeping when it is no longer in any
    status a stage reads: `enriched` and `enrichment_skipped` are in the
    export, `not_article` was retracted, and `obituary`, `opinion`,
    `weather` and the rest are kinds no enrichment stage selects, which is
    the instruction to stop rather than a record stuck.

    The outcome recorded is that status, so "what did housekeeping do" is
    answerable afterwards. A record still at `cleaned` or `labeled` keeps
    its row and the next step of the same run takes it.
    """
    closed = session.execute(
        text(
            "UPDATE pipeline_rework r SET done_at = now(), outcome = s.status "
            "FROM ("
            "  SELECT id AS rid, status, 'article' AS kind FROM articles"
            "  UNION ALL"
            "  SELECT id AS rid, status, 'candidate_link' AS kind "
            "  FROM candidate_links"
            ") s "
            "WHERE r.done_at IS NULL AND r.record_id = s.rid "
            "AND r.record_type = s.kind "
            "AND ("
            "  (r.record_type = 'article' AND s.status <> ALL(:articles))"
            "  OR (r.record_type = 'candidate_link' AND ("
            "    s.status <> ALL(:links)"
            # A FETCHED LINK IS FINISHED WITH EXTRACTION.
            #
            # A link keeps the status `article` after its fetch, and that
            # is extraction's input status -- so a row closed on status
            # alone stays open forever, while both the work queue and
            # `links_to_fetch` correctly refuse to serve a link that
            # already has an article. Seven rows sat in exactly that
            # state, and a run spent its whole window asking the queue for
            # them: "Work queue returned 0 articles - domains in cooldown,
            # will retry", batch after batch, while 158 records of real
            # work waited behind the step.
            #
            # It closes only once the ARTICLE has nothing owing either.
            # Until then the open row is what carries the article: it
            # inherits the flag through its link, which is how one run
            # takes a record from fetch to enrichment.
            # The article must EXIST and be finished. Testing only that no
            # article has work left is true for a link awaiting its FIRST
            # fetch, which would close every extract row before anything
            # was fetched -- the integration tests caught exactly that.
            "    OR ("
            "      EXISTS (SELECT 1 FROM articles a "
            "              WHERE a.candidate_link_id = r.record_id)"
            "      AND NOT EXISTS (SELECT 1 FROM articles a "
            "                      WHERE a.candidate_link_id = r.record_id "
            "                      AND a.status = ANY(:articles))"
            "    )"
            "  ))"
            ")"
        ),
        {
            "articles": _stage_statuses("article"),
            "links": _stage_statuses("candidate_link"),
        },
    ).rowcount
    session.commit()
    return closed or 0
