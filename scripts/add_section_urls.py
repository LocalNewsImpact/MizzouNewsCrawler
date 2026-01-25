#!/usr/bin/env python3
"""
Add section URLs to source metadata for enhanced discovery.

This script allows you to configure additional pages (like /news, /local,
/sports) that should be checked during URL discovery when RSS is not available.

Usage:
    # Add section URLs to a specific source
    python scripts/add_section_urls.py --host krcgtv.com \\
        --sections "/news,/local,/community"

    # Add section URLs by source name
    python scripts/add_section_urls.py --name "KRCG" \\
        --sections "/news,/local"

    # Add section URLs to multiple sources by pattern
    python scripts/add_section_urls.py --pattern "%.com" \\
        --sections "/news,/local"

    # Show current section URLs for a source
    python scripts/add_section_urls.py --host krcgtv.com --show
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import text

# Add the src directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models.database import DatabaseManager  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def add_section_urls(
    db_manager: DatabaseManager,
    host: str | None = None,
    name: str | None = None,
    pattern: str | None = None,
    sections: str | None = None,
    show: bool = False,
) -> int:
    """Add or show section URLs for sources."""
    from datetime import datetime

    if not any([host, name, pattern]):
        logger.error("Must specify --host, --name, or --pattern")
        return 1

    # Build query
    where_clauses = []
    params = {}

    if host:
        where_clauses.append("host LIKE :host")
        params["host"] = f"%{host}%"

    if name:
        where_clauses.append("canonical_name LIKE :name")
        params["name"] = f"%{name}%"

    if pattern:
        where_clauses.append("host LIKE :pattern")
        params["pattern"] = pattern

    where_sql = " AND ".join(where_clauses)

    with db_manager.get_session() as session:
        # Find matching sources
        query = text(f"""
            SELECT id, host, canonical_name, discovered_sections
            FROM sources
            WHERE {where_sql}
        """)

        results = session.execute(query, params).fetchall()

        if not results:
            logger.warning("No sources found matching criteria")
            return 1

        logger.info(f"Found {len(results)} matching source(s)")

        updated_count = 0
        for row in results:
            source_id, source_host, source_name, sections_data = row

            # Parse existing discovered_sections JSON
            if sections_data:
                if isinstance(sections_data, str):
                    current_data = json.loads(sections_data)
                else:
                    current_data = sections_data
            else:
                current_data = {}

            # Show mode
            if show:
                current_urls = current_data.get("urls", [])
                logger.info(
                    f"Source: {source_name} ({source_host})\n"
                    f"  Current section URLs: {current_urls}"
                )
                continue

            # Update mode
            if not sections:
                logger.error("Must specify --sections when updating")
                return 1

            # Parse sections input - ensure absolute URLs
            section_list = []
            for s in sections.split(","):
                s = s.strip()
                if not s:
                    continue
                # Build absolute URL if just a path
                if s.startswith("/"):
                    # Convert path to absolute URL
                    from urllib.parse import urljoin
                    abs_url = urljoin(f"https://{source_host}", s)
                    section_list.append(abs_url)
                elif s.startswith("http"):
                    # Already absolute
                    section_list.append(s)
                else:
                    # Assume it's a path without leading slash
                    from urllib.parse import urljoin
                    abs_url = urljoin(f"https://{source_host}", f"/{s}")
                    section_list.append(abs_url)

            if not section_list:
                logger.warning(f"No valid sections provided")
                continue

            # Update discovered_sections JSON structure
            old_urls = current_data.get("urls", [])
            new_data = {
                "urls": section_list,
                "discovered_at": datetime.utcnow().isoformat(),
                "discovery_method": "manual_configuration",
                "count": len(section_list),
            }

            # Save back to database
            update_query = text("""
                UPDATE sources
                SET discovered_sections = :sections,
                    section_last_updated = :updated_at
                WHERE id = :id
            """)

            session.execute(
                update_query,
                {
                    "sections": json.dumps(new_data),
                    "updated_at": datetime.utcnow(),
                    "id": source_id,
                },
            )

            logger.info(
                f"Updated {source_name} ({source_host})\n"
                f"  Old section URLs: {old_urls}\n"
                f"  New section URLs: {section_list}"
            )
            updated_count += 1

        if not show:
            session.commit()
            logger.info(f"Successfully updated {updated_count} source(s)")

    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Add section URLs to source metadata for enhanced discovery",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Add section URLs to KRCG
  python scripts/add_section_urls.py --host krcgtv.com --sections "/news,/local,/weather"

  # Show current configuration
  python scripts/add_section_urls.py --host krcgtv.com --show

  # Add sections to multiple sources
  python scripts/add_section_urls.py --pattern "%.tv" --sections "/news,/local"
        """,
    )

    parser.add_argument(
        "--host",
        help="Source hostname (partial match)",
    )

    parser.add_argument(
        "--name",
        help="Source name (partial match)",
    )

    parser.add_argument(
        "--pattern",
        help="SQL LIKE pattern for host (e.g., '%.tv')",
    )

    parser.add_argument(
        "--sections",
        help="Comma-separated list of section URLs/paths (e.g., '/news,/local,/sports')",
    )

    parser.add_argument(
        "--show",
        action="store_true",
        help="Show current section URLs without updating",
    )

    args = parser.parse_args()

    db_manager = DatabaseManager()

    return add_section_urls(
        db_manager,
        host=args.host,
        name=args.name,
        pattern=args.pattern,
        sections=args.sections,
        show=args.show,
    )


if __name__ == "__main__":
    sys.exit(main())
