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

#: WHY A RECORD HAS NO TEXT -- the status says the cause, not the result.
#:
#: These all used to be `text_unavailable`, which said only that the text was
#: missing. On 2026-10-16 all 27 WSU rows carrying it turned out to be 404s --
#: the publisher deleted the page -- and 225 Mizzou rows carried it with no
#: cause recorded anywhere. "Unavailable" sent a reviewer to find out what an
#: extractor had already known when it wrote the row.
#:
#: Every one keeps the record -- URL, headline, byline, date say the
#: publication ran the story -- and no analysis stage selects any of them, so
#: nothing is classified or enriched from a body that is not there.
#:
#: The page is gone: the fetch answered 404 or 410.
NOT_FOUND = "not_found"
#: The fetch kept failing -- timeouts, blocks, errors -- until the attempts
#: ran out. The last error goes to `metadata.refetch.last_error`.
FETCH_FAILED = "fetch_failed"
#: The URL is a PDF. No parser reads one; the page is the document.
PDF_DOCUMENT = "pdf_document"
#: The page answered, and what it served was furniture with no story in it --
#: a video page, a gallery, a shell. Not `not_article`: the record says the
#: publication ran a story at this address.
NO_STORY_TEXT = "no_story_text"
#: Written before 2026-10-16. Rows still carrying it are read, never written.
TEXT_UNAVAILABLE = "text_unavailable"

#: The cause a give-up names, as the status it files the record under.
_STATUS_FOR_OUTCOME = {
    "404": NOT_FOUND,
    "410": NOT_FOUND,
    "pdf_document": PDF_DOCUMENT,
}

_ARTICLES_TO_MARK = text("""
    SELECT a.id, a.candidate_link_id, cl.status AS link_status, a.url,
           a.raw_gcs_path,
           a.metadata::jsonb ->> 'authenticated_session' AS authenticated_session
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

#: The try `_SPEND_ATTEMPT` took, given back. Never below zero.
_REFUND_ATTEMPT = text("""
    UPDATE articles a
       SET metadata = jsonb_set(
             coalesce(a.metadata::jsonb, '{}'::jsonb),
             '{refetch,attempts}',
             to_jsonb(greatest(
               coalesce((a.metadata::jsonb -> 'refetch' ->> 'attempts')::int, 0) - 1,
               0)),
             true)::json
      FROM candidate_links cl
     WHERE cl.id = a.candidate_link_id
       AND cl.status = :refetch
       AND cl.id = ANY(:link_ids)
""")

_GIVE_UP_ARTICLE = text("""
    UPDATE articles a
       SET status = :status,
           metadata = jsonb_set(
             jsonb_set(
               coalesce(a.metadata::jsonb, '{}'::jsonb),
               '{refetch,outcome}', to_jsonb(CAST(:outcome AS text)), true),
             '{refetch,last_error}',
             to_jsonb(coalesce(
               (SELECT cl.error_message FROM candidate_links cl
                 WHERE cl.id = a.candidate_link_id), '')),
             true)::json
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


#: The page a rewound link is to be parsed from instead of fetched, with the
#: session the capture ran under. Read by extraction for a link at `refetch`.
_REPLAY_FOR_LINK = text("""
    SELECT a.metadata::jsonb -> 'refetch' ->> 'replay' AS replay,
           a.metadata::jsonb -> 'refetch' ->> 'replay_session' AS replay_session
      FROM articles a
     WHERE a.candidate_link_id = :link_id
""")


def replay_uri(raw_gcs_path: str | None, archive_root: str | None = None) -> str | None:
    """Where the capture for `raw_gcs_path` is read from on a replay.

    The archive deletes a capture 30 days after it was written (a bucket
    lifecycle rule). A replay that has to outlive that reads a copy made
    later -- the same path below `archive_root`, e.g.
    `retained/wsu-reextract-2026-10-14` -- whose 30 days start at the copy.
    """
    if not raw_gcs_path or not raw_gcs_path.startswith("gs://"):
        return None
    if not archive_root:
        return raw_gcs_path
    bucket, _, path = raw_gcs_path[len("gs://") :].partition("/")
    return f"gs://{bucket}/{archive_root.strip('/')}/{path}"


def replay_for_link(session: Session, link_id: str) -> tuple[str, bool | None] | None:
    """The capture to parse for a rewound link, and its session, or None.

    None means fetch: the rewind asked for a fetch, or recorded no capture.
    """
    row = session.execute(_REPLAY_FOR_LINK, {"link_id": link_id}).mappings().first()
    if not row or not row["replay"]:
        return None
    recorded = row["replay_session"]
    session_state = None if recorded is None else recorded in ("true", True)
    return row["replay"], session_state


class Refused(Exception):
    """The rewind was not performed, and the reason is the message."""


def mark(
    session: Session,
    article_ids: list[str],
    *,
    by: str,
    reason: str,
    dry_run: bool = False,
    replay: bool = False,
    archive_root: str | None = None,
) -> dict:
    """Rewind these articles' links so extraction will fetch them again.

    `by` and `reason` are required and stored. A body replaced without a record
    of who asked and why is indistinguishable from a body that was always
    wrong, and these rows carry a measurement somebody may later question.

    With `replay`, extraction parses the page archived at the article's
    `raw_gcs_path` (below `archive_root` when given) instead of fetching it.
    That is the rewind for a body the PARSER got wrong: the page was right,
    and fetching it again costs a request, a credentialed session and the
    host's patience, and may no longer return the same page. An article with
    no capture recorded is rewound for an ordinary fetch.
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

    marked = already = replays = 0
    now = datetime.now(timezone.utc).isoformat()
    for article_id, row in found.items():
        if row["link_status"] == REFETCH:
            already += 1
            continue
        uri = replay_uri(row["raw_gcs_path"], archive_root) if replay else None
        replays += uri is not None
        if dry_run:
            marked += 1
            continue
        record: dict = {
            "by": by.strip(),
            "reason": reason.strip(),
            "at": now,
            "previous_link_status": row["link_status"],
        }
        if uri:
            # The capture's session travels with it: a replay runs on a
            # driver that never signed in, and the row must still say
            # whether the page it holds was served to a subscriber.
            record["replay"] = uri
            record["replay_session"] = row["authenticated_session"]
        note = json.dumps(record)
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
        "replay": replays,
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
    """Spend one try on links the batch is ABOUT TO FETCH; give up on the spent.

    Charged per FETCH, not per batch. Charging every selected link cost the
    2026-09-19 ptleader run ten links: batch 1 selected 17 and reached 4,
    batch 2 selected 13 and reached 3, and the ten never reached were charged
    twice for turns they never got. The next run charged a third and logged
    "gave up on 10 link(s)" without fetching one of them.

    Bounded on the ROW, as `rework.count_attempt` bounds housekeeping: the run
    that gives up is never the run that tried before it, so three runs of
    infinite patience look exactly like one. The bound is the same
    `MAX_ATTEMPTS` and the outcome the same word, so "why did this stop" has one
    answer across stages.

    NO COMMIT HERE. The batch holds its rows under FOR UPDATE ... SKIP LOCKED,
    and a commit would release them to another worker mid-batch. The caller
    commits per article, which is where this lands -- and a charge that is
    rolled back is a try the row did not pay for, which is the right answer.
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


def refund_attempt(session: Session, link_ids: list[str]) -> None:
    """Give back the try `spend_attempt` took for a fetch that never happened.

    A credentialed fetch with no confirmed session is declined before the page
    is requested. Charging it spent the row's tries on the LOGIN, and three
    refused logins abandoned a story nobody had asked for: on 2026-10-14 a
    columbian.com row was charged a try while its login hung and the host was
    refused. The login has its own budget (`_MAX_AUTH_ATTEMPTS` per driver).

    No commit, for the reason `spend_attempt` gives.
    """
    if link_ids:
        session.execute(
            _REFUND_ATTEMPT, {"refetch": REFETCH, "link_ids": list(link_ids)}
        )


def status_for_outcome(outcome: str) -> str:
    """The status a give-up files a record under: the cause, by name."""
    return _STATUS_FOR_OUTCOME.get(str(outcome), FETCH_FAILED)


def give_up(session: Session, link_ids: list[str], *, outcome: str) -> int:
    """The text is not going to be had: keep the record, stop the asking.

    The article is filed under the status that names the cause --
    `not_found` for a 404 or 410, `pdf_document`, and `fetch_failed` for
    anything else, which is attempts running out -- with the outcome under
    `metadata.refetch.outcome` and the link's last error under
    `metadata.refetch.last_error`. The link gets back the status it had before
    the rewind if it is still waiting at `refetch`. Title, byline, date and
    the body already stored are left as they are -- what the record says the
    publication ran is exactly what must survive a fetch that failed.
    """
    if not link_ids:
        return 0
    result = session.execute(
        _GIVE_UP_ARTICLE,
        {
            "status": status_for_outcome(outcome),
            "outcome": outcome,
            "link_ids": list(link_ids),
        },
    )
    session.execute(
        _RESTORE_LINK_BY_LINK, {"refetch": REFETCH, "link_ids": list(link_ids)}
    )
    return getattr(result, "rowcount", 0)
