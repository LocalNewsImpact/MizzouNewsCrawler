"""Rewinding an article far enough that its URL can be fetched again.

Extraction refuses to re-fetch a URL whose article exists, and does so twice
over: its batch query requires ``candidate_links.status = 'article'`` AND that
no article row points at the link, and `ARTICLE_INSERT_SQL` ends
``ON CONFLICT DO NOTHING``. `link_status_repair.py` states the invariant
plainly -- "a link with an article is never re-extracted whatever it says".

That is right for ordinary operation and wrong when the stored body is not the
story. 26 articles in the WSU corpus hold a paywall teaser or nothing at all,
and we hold a subscription to every publisher concerned. Re-fetching them is
the only way to get the text, and the double refusal means a naive rewind --
setting the link back to `article` -- would fetch the page, pay for the
request, and discard the body on the conflict clause. It would look like it
worked.

WHY NOT DELETE THE ARTICLE
--------------------------
That is the obvious rewind and it destroys the reason for doing this. The
article id is what `article_labels`, `article_enrichment`, `article_places`,
`article_geoids` and `article_entities` all point at, and for these 26 rows
one of those is the study's original measurement: the CIN labels produced by
the notebook that predated this application, alongside the verbatim input it
classified. A fresh insert gets a new id and orphans all of it.

So the rewind is in place. `candidate_links.status` becomes `refetch`, which
is a status extraction reads and ordinary discovery never writes, and the
article keeps its id, its labels and its history while its body is replaced.
`refetch` also says what it is to anybody reading the table, which `article`
on a link that plainly has an article does not.

WHAT A REWIND DOES NOT TOUCH
----------------------------
Labels, enrichment, entities, places, geoids. A body that changes invalidates
the conclusions drawn from it, but invalidating them is a separate act from
re-fetching: the classify and enrich stages re-answer those questions from the
new text, and they are reached through `pipeline_rework` once the body is
there. Deciding here would re-litigate verdicts before knowing whether the
fetch even succeeded.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

#: The status a link carries while it owes a second fetch. Extraction reads it;
#: discovery never writes it, so a link at `refetch` was put there on purpose.
REFETCH = "refetch"

#: The article status when the text could not be had: the page 404s, the
#: fetch keeps failing, or what came back is a wall or furniture. The record
#: STANDS -- URL, headline, byline, date say the publication ran the story --
#: and no analysis stage selects the status, so nothing is classified or
#: enriched from a body that is not there. Distinct from `not_article`, which
#: says the page never was a story, and from `paywall`, which says why.
TEXT_UNAVAILABLE = "text_unavailable"

_ARTICLES_TO_MARK = text("""
    SELECT a.id, a.candidate_link_id, cl.status AS link_status, a.url
      FROM articles a
      JOIN candidate_links cl ON cl.id = a.candidate_link_id
     WHERE a.id = ANY(:ids)
""")

_MARK_LINK = text("UPDATE candidate_links SET status = :refetch WHERE id = :link_id")

#: The previous link status is recorded because it is the only way back: it
#: is what `give_up` restores when the fetch is not going to succeed, so the
#: link stops claiming it owes work.
_MARK_ARTICLE = text("""
    UPDATE articles
       SET metadata = jsonb_set(
             coalesce(metadata::jsonb, '{}'::jsonb),
             '{refetch}', CAST(:note AS jsonb), true)::json
     WHERE id = :id
""")

#: `dataset` is matched against the SLUG as well as the id, because the slug is
#: what a person has: `--dataset WSU-Washington-State`. Comparing it to
#: `articles.dataset_id`, which holds a UUID, matched nothing and the listing
#: reported "nothing is waiting to be fetched again" over a queue that had
#: work in it -- a wrong answer that reads exactly like the right one.
_MARKED = text("""
    SELECT a.id, a.url, a.status AS article_status, a.text_length,
           a.metadata->'refetch'->>'reason'   AS reason,
           a.metadata->'refetch'->>'by'       AS requested_by,
           a.metadata->'refetch'->>'at'       AS requested_at,
           a.metadata->'refetch'->>'previous_link_status' AS previous
      FROM articles a
      JOIN candidate_links cl ON cl.id = a.candidate_link_id
      LEFT JOIN datasets d ON d.id = a.dataset_id
     WHERE cl.status = :refetch
       AND (
             CAST(:dataset AS varchar) IS NULL
             OR a.dataset_id = CAST(:dataset AS varchar)
             OR d.slug = CAST(:dataset AS varchar)
           )
     ORDER BY a.url
""")

#: One try per batch that selects the link. `RETURNING` reads the value AFTER
#: the update, so the caller sees the count this try made.
_SPEND_ATTEMPT = text("""
    UPDATE articles a
       SET metadata = jsonb_set(
             coalesce(a.metadata::jsonb, '{}'::jsonb),
             '{refetch,attempts}',
             to_jsonb(coalesce((a.metadata::jsonb -> 'refetch' ->> 'attempts')::int, 0) + 1),
             true)::json
      FROM candidate_links cl
     WHERE cl.id = a.candidate_link_id
       AND cl.status = :refetch
       AND cl.id = ANY(:link_ids)
 RETURNING cl.id, (a.metadata::jsonb -> 'refetch' ->> 'attempts')::int
""")

_GIVE_UP_ARTICLE = text("""
    UPDATE articles a
       SET status = :status,
           metadata = jsonb_set(
             coalesce(a.metadata::jsonb, '{}'::jsonb),
             '{refetch,outcome}', to_jsonb(CAST(:outcome AS text)), true)::json
     WHERE a.candidate_link_id = ANY(:link_ids)
""")

#: Only a link still at `refetch` is put back. A 404 has already moved the
#: link on, and that answer is the better one.
_RESTORE_LINK_BY_LINK = text("""
    UPDATE candidate_links cl
       SET status = coalesce(
             a.metadata->'refetch'->>'previous_link_status', 'extracted')
      FROM articles a
     WHERE a.candidate_link_id = cl.id
       AND cl.id = ANY(:link_ids)
       AND cl.status = :refetch
""")

_RESTORE_LINK = text("""
    UPDATE candidate_links cl
       SET status = coalesce(
             a.metadata->'refetch'->>'previous_link_status', 'extracted')
      FROM articles a
     WHERE a.candidate_link_id = cl.id
       AND a.id = ANY(:ids)
       AND cl.status = :refetch
""")


class Refused(Exception):
    """The rewind was not performed, and the reason is the message."""


def mark(
    session: Session,
    article_ids: list[str],
    *,
    by: str,
    reason: str,
    dry_run: bool = False,
) -> dict:
    """Rewind these articles' links so extraction will fetch them again.

    `by` and `reason` are required and stored. A body replaced without a record
    of who asked and why is indistinguishable from a body that was always
    wrong, and these rows carry a measurement somebody may later question.
    """
    if not by or not by.strip():
        raise Refused("a rewind needs --by: who asked for it")
    if not reason or not reason.strip():
        raise Refused("a rewind needs --reason: why the stored body is wrong")
    if not article_ids:
        return {"requested": 0, "marked": 0, "already": 0, "missing": 0}

    rows = session.execute(_ARTICLES_TO_MARK, {"ids": list(article_ids)}).mappings()
    found = {r["id"]: dict(r) for r in rows}
    missing = [i for i in article_ids if i not in found]

    marked = already = 0
    now = datetime.now(timezone.utc).isoformat()
    for article_id, row in found.items():
        if row["link_status"] == REFETCH:
            already += 1
            continue
        if dry_run:
            marked += 1
            continue
        note = json.dumps(
            {
                "by": by.strip(),
                "reason": reason.strip(),
                "at": now,
                "previous_link_status": row["link_status"],
            }
        )
        session.execute(_MARK_ARTICLE, {"id": article_id, "note": note})
        session.execute(
            _MARK_LINK, {"link_id": row["candidate_link_id"], "refetch": REFETCH}
        )
        marked += 1

    if not dry_run:
        session.commit()
    return {
        "requested": len(article_ids),
        "marked": marked,
        "already": already,
        "missing": len(missing),
        "missing_ids": missing,
    }


def marked(session: Session, dataset: str | None = None) -> list[dict]:
    """Every article whose link is waiting to be fetched again."""
    rows = session.execute(_MARKED, {"refetch": REFETCH, "dataset": dataset}).mappings()
    return [dict(r) for r in rows]


def clear(session: Session, article_ids: list[str], *, dry_run: bool = False) -> int:
    """Put the links back, using the status each one had before the rewind.

    For a fetch that will not succeed -- a page with no prose, a login that
    cannot be made to work -- this is how the link stops claiming to owe work.
    """
    if not article_ids:
        return 0
    if dry_run:
        return len(
            [
                r
                for r in session.execute(
                    _ARTICLES_TO_MARK, {"ids": list(article_ids)}
                ).mappings()
                if r["link_status"] == REFETCH
            ]
        )
    result = session.execute(
        _RESTORE_LINK, {"ids": list(article_ids), "refetch": REFETCH}
    )
    session.commit()
    return getattr(result, "rowcount", 0)


def spend_attempt(session: Session, link_ids: list[str]) -> set[str]:
    """Spend one try on each rewound link in a batch; give up on the exhausted.

    Bounded on the ROW, as `rework.count_attempt` bounds housekeeping: the run
    that gives up is never the run that tried before it, so three runs of
    infinite patience look exactly like one. The bound is the same
    `MAX_ATTEMPTS` and the outcome the same word, so "why did this stop" has one
    answer across stages.

    Called AFTER the batch is selected and only for the links in it, because a
    try must be a try: spending on every rewound link before selection would
    exhaust links no batch ever reached.

    NO COMMIT HERE. The batch holds its rows under FOR UPDATE ... SKIP LOCKED,
    and a commit would release them to another worker mid-batch. The batch
    commits per article, which is where this lands.
    """
    if not link_ids:
        return set()
    from src.pipeline.rework import ABANDONED, MAX_ATTEMPTS

    result = session.execute(
        _SPEND_ATTEMPT, {"refetch": REFETCH, "link_ids": list(link_ids)}
    )
    rows = result.fetchall() if result is not None else []
    exhausted = [
        str(link_id) for link_id, attempts in rows if (attempts or 0) >= MAX_ATTEMPTS
    ]
    if exhausted:
        give_up(session, exhausted, outcome=ABANDONED)
    return set(exhausted)


def give_up(session: Session, link_ids: list[str], *, outcome: str) -> int:
    """The text is not going to be had: keep the record, stop the asking.

    The article goes to `TEXT_UNAVAILABLE` with the reason under
    `metadata.refetch.outcome`; the link gets back the status it had before
    the rewind if it is still waiting at `refetch`. Title, byline, date and
    the body already stored are left as they are -- what the record says the
    publication ran is exactly what must survive a fetch that failed.
    """
    if not link_ids:
        return 0
    result = session.execute(
        _GIVE_UP_ARTICLE,
        {"status": TEXT_UNAVAILABLE, "outcome": outcome, "link_ids": list(link_ids)},
    )
    session.execute(
        _RESTORE_LINK_BY_LINK, {"refetch": REFETCH, "link_ids": list(link_ids)}
    )
    return getattr(result, "rowcount", 0)
