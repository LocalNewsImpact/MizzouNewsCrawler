"""One story, two URLs, differing only by a front controller.

    http://www.excelsiorspringsstandard.com/index.php/news/lewis-growing-young-readers
    http://www.excelsiorspringsstandard.com/news/lewis-growing-young-readers

`/index.php` in a path is routing, not address: the CMS serves the
identical page at both, and different parts of the same site link to each
form. Discovery found both, made two links, and the story was fetched,
parsed and classified twice.

MEASURED 2026-09-14: 223 stories with a complete article on BOTH sides,
99% of them from richmond-dailynews.com and excelsiorspringsstandard.com.
`normalize_url` now strips the segment, so no new pair can be made; this
is for the ones already there.

WHAT IT DOES, and what it refuses to do.

The clean URL always survives -- it is the address the site will be
crawled at from now on, and leaving 96 records on an `index.php` URL
would mean the corpus disagreed with its own normaliser.

The best article moves to it. "Best" is how far through the pipeline it
got: enriched over cleaned over labeled. Where the better article sits on
the `index.php` link, the two are SWAPPED, so the surviving link carries
the better extraction and the duplicate link carries the other. Nothing
is deleted and the swap is reversible.

It does NOT retire the redundant article. No duplicate link in this
corpus has ever had an article -- the older `duplicates` command only
ever marked orphans -- so there is no convention for it, and inventing
one here would quietly change what every count of the corpus means. The
redundant article stays, attached to the duplicate link, and the run
reports how many there are.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from src.models.database import DatabaseManager

logger = logging.getLogger(__name__)

#: How far through the pipeline an article got. Higher survives.
PROGRESS = (
    "CASE a.status WHEN 'enriched' THEN 6 WHEN 'enrichment_skipped' THEN 5 "
    "WHEN 'cleaned' THEN 4 WHEN 'labeled' THEN 3 "
    "WHEN 'curated_out' THEN 2 ELSE 1 END"
)

#: The segment, and its equivalents on other stacks.
FRONT_CONTROLLER = r"/index\.(php|html?|cfm|aspx?|jsp)(?=/|$)"

_PAIRS = text(f"""
    WITH norm AS (
      SELECT cl.id AS link_id, cl.url, cl.status AS link_status,
             regexp_replace(cl.url, '{FRONT_CONTROLLER}', '', 'gi') AS canon,
             (cl.url ~* '{FRONT_CONTROLLER}') AS has_fc,
             a.id AS article_id, a.status AS article_status,
             a.created_at, {PROGRESS} AS progress
      FROM candidate_links cl
      JOIN articles a ON a.candidate_link_id = cl.id
    ),
    -- Only pairs that differ by the front controller and nothing else.
    pairs AS (
      SELECT canon FROM norm GROUP BY canon
      HAVING count(DISTINCT url) > 1 AND bool_or(has_fc) AND bool_or(NOT has_fc)
    ),
    ranked AS (
      SELECT n.*, row_number() OVER (
        PARTITION BY n.canon
        ORDER BY n.progress DESC, n.created_at ASC, n.article_id ASC) AS rank
      FROM norm n JOIN pairs p ON p.canon = n.canon
    )
    SELECT
      canon,
      max(link_id)      FILTER (WHERE NOT has_fc) AS clean_link,
      max(link_id)      FILTER (WHERE has_fc)     AS fc_link,
      max(link_status)  FILTER (WHERE has_fc)     AS fc_link_status,
      max(article_id)   FILTER (WHERE rank = 1)   AS best_article,
      bool_or(rank = 1 AND has_fc)                AS best_is_on_fc,
      max(article_id)   FILTER (WHERE rank > 1)   AS other_article
    FROM ranked
    GROUP BY canon
    HAVING count(*) FILTER (WHERE NOT has_fc) = 1
       AND count(*) FILTER (WHERE has_fc) = 1
    ORDER BY canon
    """)


def plan(session) -> list[dict]:
    """Every pair, and what would be done to it."""
    return [dict(row._mapping) for row in session.execute(_PAIRS).fetchall()]


def apply(session, rows: list[dict]) -> dict:
    """Carry the plan out. Returns what moved."""
    counts = {"swapped": 0, "marked": 0, "left_alone": 0, "redundant_articles": 0}
    for row in rows:
        if row["other_article"]:
            counts["redundant_articles"] += 1

        # The better article belongs on the surviving link.
        if row["best_is_on_fc"]:
            # SWAP, so the duplicate link keeps an article of its own and
            # the survivor is not left holding two.
            session.execute(
                text("UPDATE articles SET candidate_link_id = :link WHERE id = :a"),
                {"link": row["clean_link"], "a": row["best_article"]},
            )
            if row["other_article"]:
                session.execute(
                    text("UPDATE articles SET candidate_link_id = :link WHERE id = :a"),
                    {"link": row["fc_link"], "a": row["other_article"]},
                )
            counts["swapped"] += 1

        # The same guard the older `duplicates` command uses: a link
        # carrying a reviewer's verdict is not overwritten.
        moved = session.execute(
            text(
                "UPDATE candidate_links SET status = 'duplicate', error_message = :why "
                "WHERE id = :id AND status = 'extracted'"
            ),
            {
                "why": (
                    "Duplicate URL; the corpus holds this story as article "
                    f"{row['best_article']}"
                ),
                "id": row["fc_link"],
            },
        ).rowcount
        counts["marked"] += moved
        counts["left_alone"] += 1 - moved
    return counts


def add_front_controller_duplicates_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "front-controller-duplicates",
        help="One story reached the corpus twice, differing only by /index.php",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Carry it out. Without this, nothing is written.",
    )
    parser.set_defaults(func=handle_front_controller_duplicates_command)


def handle_front_controller_duplicates_command(args) -> int:
    logging.basicConfig(level=getattr(args, "log_level", "INFO"))
    db = DatabaseManager()
    with db.get_session() as session:
        rows = plan(session)
        print(f"story pairs: {len(rows)}")
        print(
            f"  best copy already on the clean URL: "
            f"{sum(1 for r in rows if not r['best_is_on_fc'])}"
        )
        print(
            f"  best copy on the index.php URL, to swap: "
            f"{sum(1 for r in rows if r['best_is_on_fc'])}"
        )
        if not args.apply:
            print("nothing written. Pass --apply to carry it out.")
            return 0
        counts = apply(session, rows)
        session.commit()
    print(
        f"swapped:  {counts['swapped']}\n"
        f"marked:   {counts['marked']} links now `duplicate`\n"
        f"left:     {counts['left_alone']} links not at `extracted`, untouched\n"
        f"NOTE:     {counts['redundant_articles']} redundant articles remain and "
        "still count; retiring them needs a convention this does not invent."
    )
    return 0
