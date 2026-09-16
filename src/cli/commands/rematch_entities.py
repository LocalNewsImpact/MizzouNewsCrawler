"""news-crawler rematch-entities — re-match stored entities to the state.

The matching rules changed (docs/STATEWIDE_GAZETTEER.md §8): exact only,
normalised properly, scoped to the states a source actually reaches. The
2.97M rows in `article_entities` were matched under the old ones -- a
0.85 similarity threshold against one publisher's 22-mile slice -- so
they have to be asked again.

spaCy is NOT re-run. `entity_text` is stored; what changed is the
normalisation, the scope and the threshold, so this re-asks the matching
question over existing rows instead of re-reading 20,521 articles.

Run AFTER `geocode-gazetteer --table gazetteer_features` and
`load-state-gazetteer --rebuild-index`: the gate reads the name index,
and a name whose features have no place counts as ambiguous.
"""

from __future__ import annotations

import argparse
import logging

logger = logging.getLogger(__name__)


def add_rematch_entities_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "rematch-entities",
        help="Re-match stored entities against the statewide gazetteer",
    )
    parser.add_argument("--source", default=None, help="one source id")
    parser.add_argument("--limit-sources", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.set_defaults(func=handle_rematch_entities_command)


def handle_rematch_entities_command(args: argparse.Namespace) -> int:
    from sqlalchemy import text

    from src.models.database import DatabaseManager
    from src.pipeline.entity_extraction import get_state_features, rematch_source
    from src.pipeline.statewide_gazetteer import scope_for

    db = DatabaseManager()
    totals = {"sources": 0, "read": 0, "matched": 0, "cleared": 0, "unchanged": 0}
    features_by_states: dict[tuple[str, ...], list] = {}

    with db.get_session() as session:
        where = "WHERE sc.source_id = :source" if args.source else ""
        limit = f"LIMIT {int(args.limit_sources)}" if args.limit_sources else ""
        sources = session.execute(
            text(f"""SELECT DISTINCT sc.source_id, s.host
                      FROM source_gazetteer_scope sc
                      JOIN sources s ON s.id = sc.source_id
                      {where}
                     ORDER BY s.host {limit}"""),
            {"source": args.source} if args.source else {},
        ).all()

        for source_id, host in sources:
            states = tuple(scope_for(session, source_id))
            if not states:
                continue
            if states not in features_by_states:
                # Fetched once per state SET: Missouri is 32,327
                # features and Washington 49,650, and a read per
                # publisher in the state is the shape that does not
                # finish.
                if len(features_by_states) >= 4:
                    features_by_states.pop(next(iter(features_by_states)))
                features_by_states[states] = get_state_features(session, list(states))
            counts = rematch_source(
                session,
                source_id,
                features_by_states[states],
                dry_run=args.dry_run,
            )
            totals["sources"] += 1
            for key in ("read", "matched", "cleared", "unchanged"):
                totals[key] += counts[key]
            if counts["read"]:
                logger.info(
                    "%s [%s]: %s read, %s matched, %s cleared",
                    host,
                    "+".join(states),
                    counts["read"],
                    counts["matched"],
                    counts["cleared"],
                )

    print(
        f"sources:   {totals['sources']}\n"
        f"read:      {totals['read']}\n"
        f"matched:   {totals['matched']}\n"
        f"cleared:   {totals['cleared']}\n"
        f"unchanged: {totals['unchanged']}"
        + ("\n(dry run — nothing written)" if args.dry_run else "")
    )
    return 0
