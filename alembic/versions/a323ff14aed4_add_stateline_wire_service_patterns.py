"""add stateline wire service patterns

Revision ID: a323ff14aed4
Revises: 43a60f360933
Create Date: 2025-12-20 14:24:17.868830

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a323ff14aed4'
down_revision: Union[str, Sequence[str], None] = '43a60f360933'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add Stateline (States Newsroom) wire service patterns
    op.execute("""
        INSERT INTO wire_services (pattern, service_name, pattern_type, case_sensitive, priority, active, notes, created_at, updated_at)
        SELECT pattern, service_name, pattern_type, case_sensitive, priority, active, notes, NOW(), NOW()
        FROM (VALUES
            -- Author byline patterns
            ('\\s*~\\s*Stateline\\b', 'Stateline', 'author', false, 100, true, 'Byline format: "By Author ~ Stateline"'),
            ('\\bStateline\\s+reporter\\b', 'Stateline', 'footer', false, 100, true, 'Footer: "Stateline reporter [Name] can be reached at..."'),
            ('@stateline\\.org', 'Stateline', 'footer', false, 100, true, 'Email attribution in footer'),

            -- Explicit republication statements
            ('originally produced by\\s+Stateline', 'Stateline', 'footer', false, 100, true, 'Syndication disclosure statement'),
            ('States Newsroom.*Missouri Independent', 'Stateline', 'footer', false, 100, true, 'Parent org mention (States Newsroom network)'),

            -- URL patterns
            ('/stateline/', 'Stateline', 'url', false, 100, true, 'URL contains /stateline/ path')
        ) AS new_patterns(pattern, service_name, pattern_type, case_sensitive, priority, active, notes)
        WHERE NOT EXISTS (
            SELECT 1 FROM wire_services ws
            WHERE ws.pattern = new_patterns.pattern
            AND ws.pattern_type = new_patterns.pattern_type
        )
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Remove Stateline patterns
    op.execute("""
        DELETE FROM wire_services
        WHERE service_name = 'Stateline'
    """)
