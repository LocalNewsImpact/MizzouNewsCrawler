"""A body already stored under other URLs of the same host is not this article's.

The existing verdict catches a wall two ways: too little text, or explicit
paywall wording. Neither caught the Port Townsend Leader's fallback page, which
is 2,215 characters of a concert listing with no subscription language in it, so
it was stored as the body of two different articles.

What gives it away is that it was already in the corpus. A body byte-identical to
one stored under a different URL of the SAME host is a wall, a search page, a
calendar notice or some other recurring furniture -- the corpus holds one
"Attention subscribers" notice under 613 West Plains Daily Quill URLs and one
restaurant-inspection explainer under 40 Examiner URLs.

EVERY SAME-HOST REPEAT, NOT JUST THE FREQUENT ONES
--------------------------------------------------
An earlier version of this left a single repeat alone, on the theory that an
outlet republishing a story at a second URL produces two real articles. It does
not produce two articles worth counting. lafayettemonews has

    /2026/03/18/commissioners-meet-with-special-road-districts/
    /2026/03/18/commissioners-meet-with-special-road-districts-2/

with the same title and the same 2,676-character body -- WordPress's `-2`
collision suffix on a story published twice. Both were `enriched`, so that story
appeared twice in everything downstream.

Furniture and a double-post are the same problem at different frequencies, and
neither is wanted. So the first body stored under a host keeps it and any later
URL carrying the identical body is a duplicate.

A cross-host repeat is never a duplicate here: syndication is the whole point of
this corpus, and 6,123 hash groups span more than one host.
"""

from __future__ import annotations

from dataclasses import dataclass

#: How many OTHER URLs of the same host may already hold this body. Zero: the
#: first row to store a body keeps it, and any later URL with the identical body
#: on that host is a duplicate whether it is furniture or a double-post.
OTHER_URL_LIMIT = 0

#: Statuses at or above this mean the server did not give us the article, so
#: whatever it rendered is not a body whatever it looks like.
ERROR_STATUS = 400


@dataclass(frozen=True)
class BodyVerdict:
    """Whether a captured body should be stored, and why not."""

    keep: bool
    reason: str | None = None
    #: True when the body is another URL's rather than absent or refused, which
    #: is a different verdict: `duplicate` names the story that survived, while
    #: `not_article` says this page never had one.
    duplicate: bool = False


def judge_body(
    *,
    same_host_url_count: int,
    http_status: int | None,
) -> BodyVerdict:
    """Decide whether a captured body belongs to the URL that was requested.

    `same_host_url_count` is how many OTHER URLs of this host already store a
    byte-identical body. `http_status` is the navigation's status where it is
    known -- None on a path that cannot report one, which is not evidence of
    anything and must not be read as failure.
    """
    if http_status is not None and http_status >= ERROR_STATUS:
        return BodyVerdict(
            keep=False,
            reason=f"http_{http_status}",
        )
    if same_host_url_count > OTHER_URL_LIMIT:
        return BodyVerdict(
            keep=False,
            reason=f"body_already_on_{same_host_url_count}_url_of_this_host",
            duplicate=True,
        )
    return BodyVerdict(keep=True)


#: How many other URLs of one host hold this exact body. Counted on
#: `ix_articles_text_hash`, so the lookup is an index scan rather than a scan of
#: the corpus, and bounded by LIMIT because the answer only has to clear a
#: threshold of 2 -- not report that 613 URLs share a notice.
#:
#: The host comes from the link rather than being passed in: the batch query does
#: not select source_id, and deriving it here keeps the caller from having to.
SAME_HOST_BODY_COUNT_SQL = """
    SELECT count(*) FROM (
      SELECT a.id
        FROM articles a
        JOIN candidate_links cl ON cl.id = a.candidate_link_id
       WHERE a.text_hash = :text_hash
         AND cl.source_id = (
               SELECT source_id FROM candidate_links WHERE id = :candidate_link_id
             )
         AND a.candidate_link_id <> :candidate_link_id
       LIMIT :probe
    ) t
"""
