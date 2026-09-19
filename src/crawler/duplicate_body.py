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

WHY NOT REFUSE EVERY REPEAT
---------------------------
An outlet does sometimes publish the same story at two URLs, and those are real
articles: excelsiorspringsstandard has a 1,062-character story at four, and
lafayettemonews a 2,676-character one at two. Refusing a body because it appears
twice would discard them.

So the threshold is how MANY other URLs already hold it. Furniture accumulates --
by the time a page has been stored under three URLs of one host it is a fixture
of the site, not a story someone republished. Two is left alone.

A cross-host repeat is never a duplicate here: syndication is the whole point of
this corpus, and 6,123 hash groups span more than one host.
"""

from __future__ import annotations

from dataclasses import dataclass

#: How many OTHER URLs of the same host must already hold this body before it is
#: read as furniture. Two copies can be a republished story; three is a fixture.
OTHER_URL_LIMIT = 2

#: Statuses at or above this mean the server did not give us the article, so
#: whatever it rendered is not a body whatever it looks like.
ERROR_STATUS = 400


@dataclass(frozen=True)
class BodyVerdict:
    """Whether a captured body should be stored, and why not."""

    keep: bool
    reason: str | None = None


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
            reason=f"body_already_on_{same_host_url_count}_urls_of_this_host",
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
