"""Create the database tables (idempotent).

This script imports the project models `Base` and calls
`Base.metadata.create_all(engine)` against the provided DB URL.

Usage:
    python scripts/create_gazetteer_table.py --db sqlite:///data/mizzou.db
"""

from __future__ import annotations

import argparse

from sqlalchemy import create_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Create DB tables (idempotent)")
    parser.add_argument(
        "--db",
        required=False,
        default="sqlite:///data/mizzou.db",
        help=("Database URL (default: sqlite:///data/mizzou.db)"),
    )
    args = parser.parse_args()

    # Import models lazily so script can be run from project root. If the
    # `src` package is not on sys.path (common when running as a script),
    # insert the repository root so the import succeeds.
    try:
        from src.models import Base  # type: ignore
    except Exception:  # pragma: no cover - environment dependent
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(repo_root))
        from src.models import Base  # type: ignore

    engine = create_engine(args.db)
    print(f"Creating tables on {args.db}...")
    Base.metadata.create_all(engine)
    print("Done.")


if __name__ == "__main__":
    main()
