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

from sqlalchemy import text

#: A link is ready to fetch when it is at this status and has no article.
#: Both conditions are extraction's own: its batch query reads
#: `candidate_links.status = 'article'` and excludes links that already
#: have an article, so a row for one of those would never close.
FETCHABLE = "article"


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
    """Flagged links that are ready to be fetched, and nothing else."""
    rows = session.execute(
        text(
            "SELECT DISTINCT cl.id FROM pipeline_rework r "
            "JOIN candidate_links cl ON cl.id = r.record_id "
            "WHERE r.record_type = 'candidate_link' AND r.done_at IS NULL "
            "AND cl.status = :fetchable "
            "AND NOT EXISTS (SELECT 1 FROM articles a "
            "                WHERE a.candidate_link_id = cl.id)"
        ),
        {"fetchable": FETCHABLE},
    ).fetchall()
    return [r[0] for r in rows]


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
            "  OR (r.record_type = 'candidate_link' AND s.status <> ALL(:links))"
            ")"
        ),
        {
            "articles": _stage_statuses("article"),
            "links": _stage_statuses("candidate_link"),
        },
    ).rowcount
    session.commit()
    return closed or 0
