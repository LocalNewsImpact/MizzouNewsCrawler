"""add_wire_service_dateline_patterns

Revision ID: 259bc609c6a3
Revises: 7d013dc70116
Create Date: 2025-11-23 09:16:17.946192

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "259bc609c6a3"
down_revision: Union[str, Sequence[str], None] = "7d013dc70116"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add dateline patterns for wire service detection."""
    # Insert dateline patterns for major wire services
    op.execute(
        """
        INSERT INTO wire_services (pattern, pattern_type, service_name, case_sensitive, priority, active, notes)
        VALUES
            -- AP dateline patterns
            ('^[A-Z][A-Z\\s,\\.''\\-]+\\s*[–—-]\\s*\\(?AP\\)?\\s*[–—-]', 'content', 'Associated Press', false, 10, true, 'AP dateline pattern: CITY (AP) —'),
            ('^[A-Z][A-Z\\s,\\.''\\-]+\\s*\\(AP\\)\\s*[–—-]', 'content', 'Associated Press', false, 10, true, 'AP dateline pattern: CITY (AP) —'),
            
            -- Reuters dateline patterns
            ('^[A-Z][A-Z\\s,\\.''\\-]+\\s*\\(Reuters\\)\\s*[–—-]', 'content', 'Reuters', false, 10, true, 'Reuters dateline pattern: CITY (Reuters) —'),
            
            -- CNN dateline patterns
            ('^[A-Z][A-Z\\s,\\.''\\-]+\\s*\\(?CNN\\)?\\s*[–—-]', 'content', 'CNN', false, 10, true, 'CNN dateline pattern: CITY (CNN) —'),
            ('\\(CNN\\)\\s*[–—-]', 'content', 'CNN', false, 15, true, 'CNN inline dateline'),
            
            -- AFP dateline patterns
            ('^[A-Z][A-Z\\s,\\.''\\-]+\\s*\\(AFP\\)\\s*[–—-]', 'content', 'AFP', false, 10, true, 'AFP dateline pattern: CITY (AFP) —'),
            
            -- Strong URL patterns (explicit wire paths)
            ('/ap-', 'url', 'Associated Press', false, 20, true, 'AP URL segment'),
            ('/wire/', 'url', 'Wire Service', false, 20, true, 'Generic wire URL segment'),
            ('/stacker/', 'url', 'Stacker', false, 20, true, 'Stacker syndication URL'),
            
            -- Section patterns (weaker signals, require additional evidence)
            ('/national/', 'url', 'National Section', false, 50, true, 'National news section - requires additional evidence'),
            ('/world/', 'url', 'World Section', false, 50, true, 'World news section - requires additional evidence')
    """
    )


def downgrade() -> None:
    """Remove dateline patterns."""
    op.execute(
        """
        DELETE FROM wire_services 
        WHERE pattern IN (
            '^[A-Z][A-Z\\s,\\.''\\-]+\\s*[–—-]\\s*\\(?AP\\)?\\s*[–—-]',
            '^[A-Z][A-Z\\s,\\.''\\-]+\\s*\\(AP\\)\\s*[–—-]',
            '^[A-Z][A-Z\\s,\\.''\\-]+\\s*\\(Reuters\\)\\s*[–—-]',
            '^[A-Z][A-Z\\s,\\.''\\-]+\\s*\\(?CNN\\)?\\s*[–—-]',
            '\\(CNN\\)\\s*[–—-]',
            '^[A-Z][A-Z\\s,\\.''\\-]+\\s*\\(AFP\\)\\s*[–—-]',
            '/ap-',
            '/wire/',
            '/stacker/',
            '/national/',
            '/world/'
        )
    """
    )
