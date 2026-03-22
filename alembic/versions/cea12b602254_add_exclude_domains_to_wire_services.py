"""add_exclude_domains_to_wire_services

Revision ID: cea12b602254
Revises: d7e8f9a0b1c2
Create Date: 2026-03-21 19:09:08.246931

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cea12b602254'
down_revision: Union[str, Sequence[str], None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add exclude_domains column to wire_services table.
    
    This column stores a comma-separated list of domains where this
    wire service pattern should NOT be applied (e.g., the wire service's
    own domain, or member sites for a consortium like MNN).
    """
    op.add_column(
        'wire_services',
        sa.Column(
            'exclude_domains',
            sa.Text(),
            nullable=True,
            comment='Comma-separated domains where this pattern should not apply'
        )
    )
    
    # Migrate hardcoded wire service domains to the database
    # These are wire service's own domains - patterns shouldn't fire there
    # Include all service_name variations (AP vs Associated Press, etc.)
    wire_service_domains = {
        # AP variations
        'AP': 'apnews.com',
        'Associated Press': 'apnews.com',
        # Reuters
        'Reuters': 'reuters.com',
        # Bloomberg
        'Bloomberg': 'bloomberg.com',
        # NPR
        'NPR': 'npr.org',
        # PBS
        'PBS': 'pbs.org',
        # CNN
        'CNN': 'cnn.com',
        # NYT
        'The New York Times': 'nytimes.com',
        # WaPo
        'The Washington Post': 'washingtonpost.com',
        # USA TODAY variations
        'USA TODAY': 'usatoday.com',
        'USA TODAY NETWORK': 'usatoday.com',
        # WSJ
        'Wall Street Journal': 'wsj.com',
        # LA Times
        'Los Angeles Times': 'latimes.com',
        # States Newsroom
        'States Newsroom': 'statesnewsroom.org,kansasreflector.com',
        # Missouri Independent
        'The Missouri Independent': 'missouriindependent.org,missouriindependent.com',
        # WAVE
        'WAVE': 'wave3.com',
        # MNN variations
        'Missouri News Network': 'komu.com,kbia.org,columbiamissourian.com,missouribusinessalert.com',
        'MNN': 'komu.com,kbia.org,columbiamissourian.com,missouribusinessalert.com',
        # AFP
        'AFP': 'afp.com',
        # UPI
        'UPI': 'upi.com',
        # Tribune
        'Tribune News Service': 'tribunecontentagency.com',
        # McClatchy
        'McClatchy': 'mcclatchy.com',
        # Gannett
        'Gannett': 'gannett.com,usatoday.com',
        # Gray
        'Gray News': 'gray.tv',
    }
    
    # Update existing patterns with their exclude_domains
    for service_name, domains in wire_service_domains.items():
        op.execute(
            sa.text(
                "UPDATE wire_services SET exclude_domains = :domains "
                "WHERE service_name = :name"
            ).bindparams(domains=domains, name=service_name)
        )


def downgrade() -> None:
    """Remove exclude_domains column from wire_services table."""
    op.drop_column('wire_services', 'exclude_domains')
