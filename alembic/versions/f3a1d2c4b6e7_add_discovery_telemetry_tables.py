"""Add discovery telemetry tables

Revision ID: f3a1d2c4b6e7
Revises: d1e2f3a4b5c6
Create Date: 2025-11-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import reflection


# revision identifiers, used by Alembic.
revision: str = "f3a1d2c4b6e7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(inspector: reflection.Inspector, table_name: str) -> bool:
    """Return True when the given table already exists."""
    try:
        return inspector.has_table(table_name)
    except Exception:
        return False


def _index_names(inspector: reflection.Inspector, table_name: str) -> set[str]:
    try:
        names: set[str] = set()
        for index in inspector.get_indexes(table_name):
            name = index.get("name")
            if name:
                names.add(name)
        return names
    except Exception:
        return set()


def _unique_constraint_names(
    inspector: reflection.Inspector,
    table_name: str,
) -> set[str]:
    try:
        constraints = inspector.get_unique_constraints(table_name)
    except Exception:
        return set()

    names: set[str] = set()
    for constraint in constraints:
        name = constraint.get("name")
        if name:
            names.add(name)
    return names


def upgrade() -> None:
    """Create discovery telemetry tables for Cloud SQL deployments."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # discovery_method_effectiveness -------------------------------------------------
    effectiveness_table = "discovery_method_effectiveness"
    effectiveness_created = False
    if not _table_exists(inspector, effectiveness_table):
        op.create_table(
            effectiveness_table,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("source_id", sa.String(), nullable=False),
            sa.Column("source_url", sa.String(), nullable=False),
            sa.Column("discovery_method", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column(
                "articles_found",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "success_rate",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
            sa.Column(
                "last_attempt",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "attempt_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "avg_response_time_ms",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
            sa.Column("last_status_codes", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint(
                "source_id",
                "discovery_method",
                name="uq_discovery_method_effectiveness_source_method",
            ),
        )
        effectiveness_created = True

    current_effectiveness_indexes = (
        set() if effectiveness_created else _index_names(inspector, effectiveness_table)
    )
    if "idx_effectiveness_source" not in current_effectiveness_indexes:
        op.create_index(
            "idx_effectiveness_source",
            effectiveness_table,
            ["source_id"],
        )
    if "idx_effectiveness_method" not in current_effectiveness_indexes:
        op.create_index(
            "idx_effectiveness_method",
            effectiveness_table,
            ["discovery_method"],
        )
    if "idx_effectiveness_success_rate" not in current_effectiveness_indexes:
        op.create_index(
            "idx_effectiveness_success_rate",
            effectiveness_table,
            ["success_rate"],
        )
    if "idx_effectiveness_last_attempt" not in current_effectiveness_indexes:
        op.create_index(
            "idx_effectiveness_last_attempt",
            effectiveness_table,
            ["last_attempt"],
        )

    if not effectiveness_created:
        existing_constraints = _unique_constraint_names(inspector, effectiveness_table)
        if (
            "uq_discovery_method_effectiveness_source_method"
            not in existing_constraints
        ):
            op.create_unique_constraint(
                "uq_discovery_method_effectiveness_source_method",
                effectiveness_table,
                ["source_id", "discovery_method"],
            )

    # http_status_tracking ----------------------------------------------------------
    status_table = "http_status_tracking"
    status_created = False
    if not _table_exists(inspector, status_table):
        op.create_table(
            status_table,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("source_id", sa.String(), nullable=False),
            sa.Column("source_url", sa.String(), nullable=False),
            sa.Column("discovery_method", sa.String(), nullable=False),
            sa.Column("attempted_url", sa.String(), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=False),
            sa.Column("status_category", sa.String(), nullable=False),
            sa.Column("response_time_ms", sa.Float(), nullable=False),
            sa.Column(
                "timestamp",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("operation_id", sa.String(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("content_length", sa.Integer(), nullable=True),
        )
        status_created = True

    current_status_indexes = (
        set() if status_created else _index_names(inspector, status_table)
    )
    if "idx_http_source_method" not in current_status_indexes:
        op.create_index(
            "idx_http_source_method",
            status_table,
            ["source_id", "discovery_method"],
        )
    if "idx_http_status_code" not in current_status_indexes:
        op.create_index(
            "idx_http_status_code",
            status_table,
            ["status_code"],
        )
    if "idx_http_timestamp" not in current_status_indexes:
        op.create_index("idx_http_timestamp", status_table, ["timestamp"])

    # discovery_outcomes ------------------------------------------------------------
    outcomes_table = "discovery_outcomes"
    outcomes_created = False
    if not _table_exists(inspector, outcomes_table):
        op.create_table(
            outcomes_table,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("operation_id", sa.String(), nullable=False),
            sa.Column("source_id", sa.String(), nullable=False),
            sa.Column("source_name", sa.String(), nullable=False),
            sa.Column("source_url", sa.String(), nullable=False),
            sa.Column("outcome", sa.String(), nullable=False),
            sa.Column(
                "articles_found",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "articles_new",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "articles_duplicate",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "articles_expired",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("methods_attempted", sa.Text(), nullable=False),
            sa.Column("method_used", sa.String(), nullable=True),
            sa.Column("error_details", sa.Text(), nullable=True),
            sa.Column("http_status", sa.Integer(), nullable=True),
            sa.Column(
                "discovery_time_ms",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
            sa.Column(
                "is_success",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "is_content_success",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "is_technical_failure",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("metadata", sa.Text(), nullable=True),
            sa.Column(
                "timestamp",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        outcomes_created = True

    current_outcome_indexes = (
        set() if outcomes_created else _index_names(inspector, outcomes_table)
    )
    if "idx_discovery_operation" not in current_outcome_indexes:
        op.create_index(
            "idx_discovery_operation",
            outcomes_table,
            ["operation_id"],
        )
    if "idx_discovery_source" not in current_outcome_indexes:
        op.create_index(
            "idx_discovery_source",
            outcomes_table,
            ["source_id"],
        )
    if "idx_discovery_outcome" not in current_outcome_indexes:
        op.create_index(
            "idx_discovery_outcome",
            outcomes_table,
            ["outcome"],
        )
    if "idx_discovery_success" not in current_outcome_indexes:
        op.create_index(
            "idx_discovery_success",
            outcomes_table,
            ["is_success"],
        )
    if "idx_discovery_content_success" not in current_outcome_indexes:
        op.create_index(
            "idx_discovery_content_success",
            outcomes_table,
            ["is_content_success"],
        )
    if "idx_discovery_timestamp" not in current_outcome_indexes:
        op.create_index(
            "idx_discovery_timestamp",
            outcomes_table,
            ["timestamp"],
        )
    if "idx_discovery_source_outcome" not in current_outcome_indexes:
        op.create_index(
            "idx_discovery_source_outcome",
            outcomes_table,
            ["source_id", "outcome"],
        )


def downgrade() -> None:
    """Drop discovery telemetry tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name.lower() == "sqlite"

    outcomes_table = "discovery_outcomes"
    if _table_exists(inspector, outcomes_table):
        current_outcome_indexes = _index_names(inspector, outcomes_table)
        if "idx_discovery_source_outcome" in current_outcome_indexes:
            op.drop_index("idx_discovery_source_outcome", table_name=outcomes_table)
        if "idx_discovery_timestamp" in current_outcome_indexes:
            op.drop_index("idx_discovery_timestamp", table_name=outcomes_table)
        if "idx_discovery_content_success" in current_outcome_indexes:
            op.drop_index("idx_discovery_content_success", table_name=outcomes_table)
        if "idx_discovery_success" in current_outcome_indexes:
            op.drop_index("idx_discovery_success", table_name=outcomes_table)
        if "idx_discovery_outcome" in current_outcome_indexes:
            op.drop_index("idx_discovery_outcome", table_name=outcomes_table)
        if "idx_discovery_source" in current_outcome_indexes:
            op.drop_index("idx_discovery_source", table_name=outcomes_table)
        if "idx_discovery_operation" in current_outcome_indexes:
            op.drop_index("idx_discovery_operation", table_name=outcomes_table)
        op.drop_table(outcomes_table)

    status_table = "http_status_tracking"
    if _table_exists(inspector, status_table):
        current_status_indexes = _index_names(inspector, status_table)
        if "idx_http_timestamp" in current_status_indexes:
            op.drop_index("idx_http_timestamp", table_name=status_table)
        if "idx_http_status_code" in current_status_indexes:
            op.drop_index("idx_http_status_code", table_name=status_table)
        if "idx_http_source_method" in current_status_indexes:
            op.drop_index("idx_http_source_method", table_name=status_table)
        op.drop_table(status_table)

    effectiveness_table = "discovery_method_effectiveness"
    if _table_exists(inspector, effectiveness_table):
        current_effectiveness_indexes = _index_names(inspector, effectiveness_table)
        if "idx_effectiveness_last_attempt" in current_effectiveness_indexes:
            op.drop_index(
                "idx_effectiveness_last_attempt",
                table_name=effectiveness_table,
            )
        if "idx_effectiveness_success_rate" in current_effectiveness_indexes:
            op.drop_index(
                "idx_effectiveness_success_rate",
                table_name=effectiveness_table,
            )
        if "idx_effectiveness_method" in current_effectiveness_indexes:
            op.drop_index("idx_effectiveness_method", table_name=effectiveness_table)
        if "idx_effectiveness_source" in current_effectiveness_indexes:
            op.drop_index("idx_effectiveness_source", table_name=effectiveness_table)
        existing_constraints = _unique_constraint_names(inspector, effectiveness_table)
        if (
            not is_sqlite
            and "uq_discovery_method_effectiveness_source_method"
            in existing_constraints
        ):
            op.drop_constraint(
                "uq_discovery_method_effectiveness_source_method",
                effectiveness_table,
                type_="unique",
            )
        op.drop_table(effectiveness_table)
