"""add_wire_service_author_patterns

Revision ID: f224b4c09ef3
Revises: 259bc609c6a3
Create Date: 2025-11-25 07:34:42.986988

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f224b4c09ef3'
down_revision: Union[str, Sequence[str], None] = '259bc609c6a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add author pattern type for wire service detection in byline/author fields."""
    op.execute(
        """
        INSERT INTO wire_services (pattern, pattern_type, service_name, case_sensitive, priority, active, notes)
        VALUES
            -- Explicit wire service names in author/byline (STRONGEST SIGNALS)
            ('\\bAssociated Press\\b', 'author', 'Associated Press', false, 5, true, 'AP full name in byline'),
            ('\\bThe Associated Press\\b', 'author', 'Associated Press', false, 5, true, 'AP with "The" prefix'),
            (' - Associated Press', 'author', 'Associated Press', false, 5, true, 'AP with dash separator'),
            ('\\bReuters\\b', 'author', 'Reuters', false, 5, true, 'Reuters in byline'),
            ('\\bCNN\\b', 'author', 'CNN', false, 5, true, 'CNN in byline'),
            ('\\bBloomberg\\b', 'author', 'Bloomberg', false, 5, true, 'Bloomberg in byline'),
            ('\\bNPR\\b', 'author', 'NPR', false, 5, true, 'NPR in byline'),
            ('\\bPBS\\b', 'author', 'PBS', false, 5, true, 'PBS in byline'),
            ('\\bAFP\\b', 'author', 'AFP', false, 5, true, 'AFP in byline'),
            ('\\bAgence France-Presse\\b', 'author', 'AFP', false, 5, true, 'AFP full name'),
            ('\\bUSA TODAY\\b', 'author', 'USA TODAY', false, 5, true, 'USA TODAY in byline'),
            ('\\bThe New York Times\\b', 'author', 'The New York Times', false, 5, true, 'NYT in byline'),
            ('\\bThe Washington Post\\b', 'author', 'The Washington Post', false, 5, true, 'WaPo in byline'),
            ('\\bWall Street Journal\\b', 'author', 'Wall Street Journal', false, 5, true, 'WSJ in byline'),
            ('\\bLos Angeles Times\\b', 'author', 'Los Angeles Times', false, 5, true, 'LA Times in byline'),
            ('\\bTribune News Service\\b', 'author', 'Tribune News Service', false, 5, true, 'Tribune syndication'),
            ('\\bMcClatchy\\b', 'author', 'McClatchy', false, 5, true, 'McClatchy syndication'),
            ('\\bGannett\\b', 'author', 'Gannett', false, 5, true, 'Gannett syndication'),
            ('\\bStates Newsroom\\b', 'author', 'States Newsroom', false, 5, true, 'States Newsroom syndication'),
            ('\\bStacker\\b', 'author', 'Stacker', false, 5, true, 'Stacker syndication'),
            ('\\bCNN Newsource\\b', 'author', 'CNN', false, 5, true, 'CNN syndication service'),
            
            -- Short form patterns (require word boundaries to avoid false positives)
            ('\\bAP\\b', 'author', 'Associated Press', false, 10, true, 'AP abbreviation in byline'),
            
            -- Via/Source patterns (weaker signals)
            ('Via Newsource', 'author', 'Newsource', false, 15, true, 'Newsource attribution'),
            ('Getty Images', 'author', 'Getty Images', false, 15, true, 'Getty photo credit (may be wire)')
    """
    )


def downgrade() -> None:
    """Remove author patterns."""
    op.execute(
        """
        DELETE FROM wire_services 
        WHERE pattern_type = 'author'
        AND pattern IN (
            '\\bAssociated Press\\b',
            '\\bThe Associated Press\\b',
            ' - Associated Press',
            '\\bReuters\\b',
            '\\bCNN\\b',
            '\\bBloomberg\\b',
            '\\bNPR\\b',
            '\\bPBS\\b',
            '\\bAFP\\b',
            '\\bAgence France-Presse\\b',
            '\\bUSA TODAY\\b',
            '\\bThe New York Times\\b',
            '\\bThe Washington Post\\b',
            '\\bWall Street Journal\\b',
            '\\bLos Angeles Times\\b',
            '\\bTribune News Service\\b',
            '\\bMcClatchy\\b',
            '\\bGannett\\b',
            '\\bStates Newsroom\\b',
            '\\bStacker\\b',
            '\\bCNN Newsource\\b',
            '\\bAP\\b',
            'Via Newsource',
            'Getty Images'
        )
    """
    )
