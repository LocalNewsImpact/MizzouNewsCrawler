"""Adding a place by hand, and seeing what has been added."""

from __future__ import annotations

import argparse


def add_manual_gazetteer_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "gazetteer-place",
        help="Add a place the surveys missed, or list what has been added",
    )
    parser.add_argument(
        "--state", default=None, help="USPS code, e.g. MO (required to add)"
    )
    parser.add_argument(
        "--name",
        default=None,
        help="the name as a story writes it, e.g. 'Tolton Catholic High School'",
    )
    parser.add_argument(
        "--place",
        default=None,
        help="the town it is in, as the Census writes it, e.g. Columbia",
    )
    parser.add_argument(
        "--category", default="manual", help="schools, religious, government, ..."
    )
    parser.add_argument("--by", default=None, help="who is adding it")
    parser.add_argument("--note", default="", help="why, for whoever reads it next")
    parser.add_argument(
        "--list", action="store_true", help="show what has been added and stop"
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.set_defaults(func=handle_manual_gazetteer_command)


def handle_manual_gazetteer_command(args: argparse.Namespace) -> int:
    from src.models.database import DatabaseManager
    from src.pipeline import manual_gazetteer as mg

    db = DatabaseManager()
    with db.get_session() as session:
        if args.list or not (args.name or args.place):
            rows = mg.added_places(session, state=args.state, limit=args.limit)
            if not rows:
                print("nothing has been added by hand yet")
                return 0
            print(f"{len(rows)} added by hand\n")
            for row in rows:
                # What the INDEX says, not what was asked for: an entry can
                # be present and still answer nothing, because a name borne
                # elsewhere in the state locates nowhere.
                answer = (
                    f"-> {row['resolves_to']}"
                    if row["resolves_to"]
                    else "-> (ambiguous, answers nothing)"
                )
                print(f"  {row['state']}  {row['name'][:40]:42} {answer}")
                print(
                    f"      {row['category']}, by {row['added_by'] or '?'}"
                    f"{', ' + row['note'] if row['note'] else ''}"
                )
            return 0

        missing = [
            flag
            for flag, value in (
                ("--state", args.state),
                ("--name", args.name),
                ("--place", args.place),
                ("--by", args.by),
            )
            if not value
        ]
        if missing:
            print(f"adding a place needs {', '.join(missing)}")
            return 1

        try:
            added = mg.add_place(
                session,
                state=args.state,
                name=args.name,
                place=args.place,
                category=args.category,
                added_by=args.by,
                note=args.note,
            )
        except mg.Refused as exc:
            print(f"refused: {exc}")
            return 1

        print(f"added {added['name']} -> {added['place']} ({added['state']})")
        if added["ambiguous"]:
            print(
                "  WARNING: that name is borne elsewhere in the state, so the "
                "index answers nothing for it. The entry is kept; the name is "
                "not usable as evidence until the other bearer is resolved."
            )
        if added["shared_with"]:
            print(f"  also held as: {', '.join(added['shared_with'])}")
        return 0
