"""Add a wire URL pattern to the pre-StorySniffer filter table.

This inserts (or re-activates) a `wire_services` row used by
`ContentTypeDetector._get_wire_service_patterns(pattern_type="url")`.
These patterns are checked before StorySniffer and immediately mark
matching URLs as wire-filtered.

Pattern:
- service_name: Wire Service (national)
- pattern_type: url
- pattern: /national-news(/|$)
- case_sensitive: False
- priority: 10 (higher priority than default 100)

Run in production via kubectl per DB protocol.
"""

from __future__ import annotations

import sys
from datetime import datetime

from sqlalchemy import and_

from src.models.database import DatabaseManager
from src.models import WireService


SERVICE_NAME = "Wire Service (national)"
PATTERN_TYPE = "url"
PATTERN_REGEX = r"/national-news(/|$)"
CASE_SENSITIVE = False
PRIORITY = 10
NOTES = "Global path indicates syndicated national news section"


def upsert_wire_service_url_pattern() -> bool:
    """Insert or update the wire service URL pattern.

    Returns True if a change was made (insert/update), False if already present.
    """

    db = DatabaseManager()
    changed = False

    with db.get_session() as session:
        existing = (
            session.query(WireService)
            .filter(
                and_(
                    WireService.pattern_type == PATTERN_TYPE,
                    WireService.pattern == PATTERN_REGEX,
                )
            )
            .one_or_none()
        )

        if existing:
            updates = []
            if not existing.active:
                existing.active = True
                updates.append("active=True")
            if existing.service_name != SERVICE_NAME:
                existing.service_name = SERVICE_NAME
                updates.append(f"service_name='{SERVICE_NAME}'")
            if bool(existing.case_sensitive) != bool(CASE_SENSITIVE):
                existing.case_sensitive = bool(CASE_SENSITIVE)
                updates.append(f"case_sensitive={CASE_SENSITIVE}")
            if int(existing.priority or 100) != int(PRIORITY):
                existing.priority = int(PRIORITY)
                updates.append(f"priority={PRIORITY}")
            if (existing.notes or "") != NOTES:
                existing.notes = NOTES
                updates.append("notes updated")

            if updates:
                existing.updated_at = datetime.utcnow()
                session.add(existing)
                session.commit()
                changed = True
                print(
                    f"Updated wire_services pattern id={existing.id}: " + ", ".join(updates)
                )
            else:
                print(
                    f"Pattern already present and active (id={existing.id}, regex='{PATTERN_REGEX}')"
                )
        else:
            new_row = WireService(
                service_name=SERVICE_NAME,
                pattern=PATTERN_REGEX,
                pattern_type=PATTERN_TYPE,
                case_sensitive=bool(CASE_SENSITIVE),
                priority=int(PRIORITY),
                active=True,
                notes=NOTES,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(new_row)
            session.commit()
            changed = True
            print(
                f"Inserted wire_services pattern (id={new_row.id}, type='{PATTERN_TYPE}', regex='{PATTERN_REGEX}')"
            )

    return changed


def main() -> None:
    print("Adding pre-StorySniffer wire URL pattern: '/national-news' → wire")
    try:
        changed = upsert_wire_service_url_pattern()
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: failed to upsert wire_services pattern: {exc}")
        sys.exit(1)

    if changed:
        print("Done. Pattern is active and prioritized.")
    else:
        print("No changes needed. Pattern already active.")

    print(
        "\nRun in production via:\n"
        "kubectl exec -n production deployment/mizzou-api -- python -m scripts.add_wire_service_url_pattern\n"
        "\nVerify presence (read-only):\n"
        "kubectl exec -n production deployment/mizzou-api -- python -c \"\n"
        "from src.models.database import DatabaseManager; from sqlalchemy import text; db = DatabaseManager();\n"
        "with db.get_session() as s:\n"
        "    q = s.execute(text(\'SELECT service_name, pattern_type, pattern, priority, active FROM wire_services WHERE pattern_type=\\\'url\\\' AND pattern=\\\'/national-news(/|$)\\\'\'));\n"
        "    print([tuple(r) for r in q.fetchall()])\n"
        "\"\n"
    )


if __name__ == "__main__":
    main()
