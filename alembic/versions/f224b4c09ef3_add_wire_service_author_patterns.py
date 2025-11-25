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
        INSERT INTO wire_services (pattern, pattern_type, service_name, case_sensitive, priority, active, notes, created_at, updated_at)
        VALUES
            -- Explicit wire service names in author/byline (STRONGEST SIGNALS)
            ('\\bAssociated Press\\b', 'author', 'Associated Press', false, 5, true, 'AP full name in byline', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bThe Associated Press\\b', 'author', 'Associated Press', false, 5, true, 'AP with "The" prefix', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            (' - Associated Press', 'author', 'Associated Press', false, 5, true, 'AP with dash separator', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bReuters\\b', 'author', 'Reuters', false, 5, true, 'Reuters in byline', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bCNN\\b', 'author', 'CNN', false, 5, true, 'CNN in byline', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bBloomberg\\b', 'author', 'Bloomberg', false, 5, true, 'Bloomberg in byline', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bNPR\\b', 'author', 'NPR', false, 5, true, 'NPR in byline', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bPBS\\b', 'author', 'PBS', false, 5, true, 'PBS in byline', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bAFP\\b', 'author', 'AFP', false, 5, true, 'AFP in byline', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bAgence France-Presse\\b', 'author', 'AFP', false, 5, true, 'AFP full name', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bUSA TODAY\\b', 'author', 'USA TODAY', false, 5, true, 'USA TODAY in byline', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bThe New York Times\\b', 'author', 'The New York Times', false, 5, true, 'NYT in byline', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bThe Washington Post\\b', 'author', 'The Washington Post', false, 5, true, 'WaPo in byline', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bWall Street Journal\\b', 'author', 'Wall Street Journal', false, 5, true, 'WSJ in byline', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bLos Angeles Times\\b', 'author', 'Los Angeles Times', false, 5, true, 'LA Times in byline', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bTribune News Service\\b', 'author', 'Tribune News Service', false, 5, true, 'Tribune syndication', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bMcClatchy\\b', 'author', 'McClatchy', false, 5, true, 'McClatchy syndication', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bGannett\\b', 'author', 'Gannett', false, 5, true, 'Gannett syndication', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bStates Newsroom\\b', 'author', 'States Newsroom', false, 5, true, 'States Newsroom syndication', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bStacker\\b', 'author', 'Stacker', false, 5, true, 'Stacker syndication', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('\\bCNN Newsource\\b', 'author', 'CNN', false, 5, true, 'CNN syndication service', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            
            -- Short form patterns (require word boundaries to avoid false positives)
            ('\\bAP\\b', 'author', 'Associated Press', false, 10, true, 'AP abbreviation in byline', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            
            -- Via/Source patterns (weaker signals)
            ('Via Newsource', 'author', 'Newsource', false, 15, true, 'Newsource attribution', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('Getty Images', 'author', 'Getty Images', false, 15, true, 'Getty photo credit (may be wire)', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
