"""Add a global URL verification pattern for wire content.

This script inserts (or re-activates) a dynamic verification pattern into the
`verification_patterns` table so discovery-stage URL verification suppresses
wire service content early.

Pattern added:
- pattern_type: wire
- pattern_regex: /national-news(/|$)
- description: Global: URLs under a `national-news` section are syndicated/wire

Run this in production via kubectl exec (see README output when executed).
"""

from __future__ import annotations

import sys
from datetime import datetime

from sqlalchemy import and_

from src.models.database import DatabaseManager
from src.models.verification import VerificationPattern


PATTERN_TYPE = "wire"
PATTERN_REGEX = r"/national-news(/|$)"
PATTERN_DESCRIPTION = (
    "Global: paths containing '/national-news' indicate syndicated/wire content"
)


def upsert_wire_pattern() -> bool:
    """Insert or re-activate the 'national-news' wire URL pattern.

    Returns True if a change was made (insert/update), False if already present.
    """

    db = DatabaseManager()
    changed = False

    with db.get_session() as session:
        existing = (
            session.query(VerificationPattern)
            .filter(
                and_(
                    VerificationPattern.pattern_type == PATTERN_TYPE,
                    VerificationPattern.pattern_regex == PATTERN_REGEX,
                )
            )
            .one_or_none()
        )

        if existing:
            if not existing.is_active or (existing.pattern_description or "") != PATTERN_DESCRIPTION:
                existing.is_active = True
                existing.pattern_description = PATTERN_DESCRIPTION
                existing.updated_at = datetime.utcnow()
                session.add(existing)
                session.commit()
                changed = True
                print(
                    f"Updated existing pattern {existing.id}: set active=True, description='{PATTERN_DESCRIPTION}'"
                )
            else:
                print(
                    f"Pattern already present and active (id={existing.id}, regex='{PATTERN_REGEX}')"
                )
        else:
            new_row = VerificationPattern(
                pattern_type=PATTERN_TYPE,
                pattern_regex=PATTERN_REGEX,
                pattern_description=PATTERN_DESCRIPTION,
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(new_row)
            session.commit()
            changed = True
            print(
                f"Inserted new verification pattern (id={new_row.id}, type='{PATTERN_TYPE}', regex='{PATTERN_REGEX}')"
            )

    return changed


def main() -> None:
    print("Adding global wire URL pattern: '/national-news' → status='wire'")
    try:
        changed = upsert_wire_pattern()
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: failed to upsert verification pattern: {exc}")
        sys.exit(1)

    if changed:
        print("Done. Pattern is active and will be picked up by URL verification.")
    else:
        print("No changes needed. Pattern already active.")

    print(
        "\nRun in production via:\n"
        "kubectl exec -n production deployment/mizzou-api -- python -m scripts.add_wire_url_pattern\n"
        "\nTo verify suppression (read-only sample):\n"
        "kubectl exec -n production deployment/mizzou-api -- python -c \"\n"
        "from src.models.database import DatabaseManager; from sqlalchemy import text; db = DatabaseManager();\n"
        "with db.get_session() as s:\n"
        "    q = s.execute(text(\'SELECT COUNT(*) FROM candidate_links WHERE url ILIKE \\\'%/national-news/%\\\' AND status = \\\'wire\\\'\'));\n"
        "    print('national-news wire URLs:', q.scalar())\n"
        "\"\n"
    )


if __name__ == "__main__":
    main()
