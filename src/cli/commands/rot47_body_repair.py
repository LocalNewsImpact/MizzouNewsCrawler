"""Decode the bodies that were stored as ciphertext.

TownNews and Lee sites serve paywalled prose ROT47-encoded, and 5,377
articles hold it undecoded -- 1,086 of them published in March 2026, of
which 135 are `enriched` and 27 `labeled`: in the export, counted as
local coverage, with ciphertext where the story should be.

They are not waiting on a fix. Run against production on 2026-09-08, the
decoder already in the tree read 298 of 300 March bodies cleanly, and the
0.4 letter-ratio gate that was the suspected cause rejected none of 905
segments (median ratio 0.812). These rows were extracted before the
decoder was repaired and nothing has passed over them since.

WHY NOT `clean-articles`
------------------------
That command decodes too, but it selects by status and writes status
back: it re-runs the balanced cleaner, redoes wire detection and can move
an article between `wire`, `local` and `extracted`. Pointed at 135
enriched rows it would do considerably more than decode them, and the
status on those rows was decided on other evidence.

This repairs a body and touches nothing else. The status stays whatever
it was, because whether an article is wire or weather or local is not a
question about its encoding, and answering it again here would silently
re-litigate 5,377 verdicts a person may already have reviewed.
"""

import argparse
import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: `k^Am` is ROT47 for `</p>`, so it appears in every encoded body and in
#: no decoded one. Cheaper and more exact than re-running the detector.
CIPHERTEXT_MARKER = "k^Am"

FIND_SQL = text("""
    SELECT a.id, a.content, a.text
      FROM articles a
     WHERE a.content LIKE '%k^Am%'
       AND (CAST(:since AS date) IS NULL OR a.publish_date >= CAST(:since AS date))
       AND (CAST(:until AS date) IS NULL OR a.publish_date < CAST(:until AS date))
     ORDER BY a.publish_date DESC NULLS LAST
     LIMIT :limit
    """)

#: Status is absent on purpose. So is `wire`: this rewrites what the body
#: says, not what anybody concluded from it.
REPAIR_SQL = text("""
    UPDATE articles
       SET content = :content,
           text = :text,
           text_hash = :text_hash,
           text_excerpt = :excerpt
     WHERE id = :id
    """)


def add_rot47_body_repair_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "repair-rot47-bodies",
        help="Decode article bodies still stored as ROT47 ciphertext",
    )
    parser.add_argument(
        "--since", help="Only articles published on or after this date (YYYY-MM-DD)"
    )
    parser.add_argument("--until", help="Exclusive upper bound, same format")
    parser.add_argument(
        "--limit", type=int, default=1000, help="Articles per run (default: 1000)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would decode and write nothing",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    parser.set_defaults(func=handle_rot47_body_repair_command)
    return parser


def handle_rot47_body_repair_command(args) -> int:
    logging.basicConfig(level=getattr(logging, args.log_level))

    from src.models.database import DatabaseManager, calculate_content_hash
    from src.pipeline.text_cleaning import decode_rot47_segments

    repaired = unchanged = failed = 0
    db = DatabaseManager()
    with db.get_session() as session:
        # The scan is a full pass over a 286 MB table and the default two
        # minutes does not cover it.
        session.execute(text("SET statement_timeout = '900s'"))
        rows = session.execute(
            FIND_SQL,
            {"since": args.since, "until": args.until, "limit": args.limit},
        ).fetchall()
        logger.info("Found %d articles holding ciphertext", len(rows))

        for article_id, content, body_text in rows:
            try:
                decoded = decode_rot47_segments(content)
            except Exception:
                logger.exception("Decoder raised on %s", article_id)
                failed += 1
                continue

            # Still encoded, or the decoder declined: leave it exactly as
            # it is. A partial decode written back is worse than
            # ciphertext, because the marker that finds these rows again
            # would be gone.
            if not decoded or CIPHERTEXT_MARKER in decoded or decoded == content:
                unchanged += 1
                continue

            # `text` is the cleaned body and holds the same ciphertext on
            # all but 115 of these rows. Decoded from its own value rather
            # than copied from `content`, which is the raw capture and was
            # never the same string.
            decoded_text = decode_rot47_segments(body_text) if body_text else None
            final_text = decoded_text or decoded

            if not args.dry_run:
                session.execute(
                    REPAIR_SQL,
                    {
                        "id": article_id,
                        "content": decoded,
                        "text": final_text,
                        "text_hash": calculate_content_hash(final_text),
                        "excerpt": final_text[:500],
                    },
                )
            repaired += 1

        if not args.dry_run:
            session.commit()

    print(f"found:     {repaired + unchanged + failed}")
    print(f"decoded:   {repaired}{' (dry run)' if args.dry_run else ''}")
    print(f"unchanged: {unchanged}  (decoder declined; still ciphertext)")
    print(f"failed:    {failed}")
    return 0
