"""Discovery status command for the modular CLI."""

import argparse
import logging

from sqlalchemy import text

from src.models.database import DatabaseManager, safe_execute


def add_discovery_status_parser(subparsers) -> argparse.ArgumentParser:
    """Add discovery-status command parser to subparsers."""
    parser = subparsers.add_parser(
        "discovery-status",
        help="Show discovery pipeline status and source scheduling information",
    )

    parser.add_argument(
        "--dataset",
        type=str,
        help="Filter to specific dataset label",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed source information",
    )

    parser.set_defaults(func=handle_discovery_status_command)
    return parser


def handle_discovery_status_command(args) -> int:
    """Handle the discovery-status command."""
    logger = logging.getLogger(__name__)

    try:
        from src.crawler.discovery import NewsDiscovery

        database_url = "sqlite:///data/mizzou.db"

        print("\n📊 Discovery Pipeline Status")
        print("=" * 70)

        db = DatabaseManager(database_url)

        # Show datasets
        with db.engine.connect() as conn:
            datasets = safe_execute(
                conn, text("SELECT label, slug, created_at FROM datasets ORDER BY label")
            ).fetchall()

            print(f"\n📁 Datasets ({len(datasets)}):")
            if datasets:
                for ds in datasets:
                    print(f"   • {ds[0]}")
                    if args.verbose:
                        print(f"     Slug: {ds[1]}")
                        print(f"     Created: {ds[2]}")
            else:
                print("   (No datasets found)")

        # Show source counts
        dataset_label = getattr(args, "dataset", None)
        with db.engine.connect() as conn:
            if dataset_label:
                result = safe_execute(
                    conn,
                    text(
                        """
                        SELECT COUNT(DISTINCT s.id)
                        FROM sources s
                        JOIN dataset_sources ds ON s.id = ds.source_id
                        JOIN datasets d ON ds.dataset_id = d.id
                        WHERE d.label = :label
                        """
                    ),
                    {"label": dataset_label},
                ).fetchone()
                scope = f" (dataset: {dataset_label})"
            else:
                result = safe_execute(conn, text("SELECT COUNT(*) FROM sources")).fetchone()
                scope = " (all datasets)"

            total_sources = result[0] if result else 0

            print(f"\n🗂️  Total Sources{scope}: {total_sources}")

        if total_sources == 0:
            print("\n⚠️  No sources found. Load sources with:")
            print("    python -m src.cli load-sources --csv sources/publinks.csv")
            return 1

        # Show sources by discovery status
        discovery = NewsDiscovery(database_url=database_url)

        # Get all sources (no filtering)
        sources_df, stats = discovery.get_sources_to_process(
            dataset_label=dataset_label, due_only=False
        )

        print("\n⏰ Discovery Status:")
        if not sources_df.empty:
            never_attempted = len(sources_df[sources_df["discovery_attempted"] == 0])
            previously_attempted = len(
                sources_df[sources_df["discovery_attempted"] == 1]
            )

            print(f"   • Never attempted: {never_attempted}")
            print(f"   • Previously attempted: {previously_attempted}")

            if args.verbose and never_attempted > 0:
                print("\n   Sources never attempted:")
                for _, row in (
                    sources_df[sources_df["discovery_attempted"] == 0]
                    .head(10)
                    .iterrows()
                ):
                    print(f"      - {row['name']}")
                if never_attempted > 10:
                    print(f"      ... and {never_attempted - 10} more")
        else:
            print("   (No sources match filters)")

        # Show what would run with --due-only
        sources_df_due, stats_due = discovery.get_sources_to_process(
            dataset_label=dataset_label, due_only=True
        )

        print("\n✅ Scheduled Discovery (--due-only behavior):")
        print(f"   • Sources due now: {len(sources_df_due)}")
        print(f"   • Sources skipped: {stats_due.get('sources_skipped', 0)}")

        if len(sources_df_due) == 0 and total_sources > 0:
            print("\n⚠️  No sources are currently due for discovery.")
            print("    This is normal for sources recently discovered.")
            print("    Use --force-all to override scheduling:")
            print(
                f"    python -m src.cli discover-urls "
                f"{'--dataset ' + dataset_label if dataset_label else ''} --force-all"
            )

        # Show recent discovery activity
        with db.engine.connect() as conn:
            recent = safe_execute(
                conn,
                text(
                    """
                    SELECT 
                        DATE(discovered_at) as discovery_date,
                        COUNT(*) as url_count
                    FROM candidate_links
                    WHERE discovered_at >= DATE('now', '-7 days')
                    GROUP BY DATE(discovered_at)
                    ORDER BY discovery_date DESC
                    LIMIT 7
                    """
                ),
            ).fetchall()

            if recent:
                print("\n📈 Recent Discovery Activity (last 7 days):")
                for row in recent:
                    print(f"   • {row[0]}: {row[1]} URLs discovered")
            else:
                print("\n📈 Recent Discovery Activity: None in last 7 days")

        print("\n" + "=" * 70)
        return 0

    except Exception as exc:
        logger.exception("Discovery status command failed")
        print(f"❌ Discovery status command failed: {exc}")
        return 1
