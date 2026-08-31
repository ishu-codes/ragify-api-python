"""credits, storage caps, rate limits

Revision ID: 02
Revises: 01
Create Date: 2026-08-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "02"
down_revision: Union[str, None] = "01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "credit_balance",
            sa.Integer(),
            server_default=sa.text("50"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "credit_period_start",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "storage_bytes",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )

    op.create_table(
        "credit_ledger",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=50), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_credit_ledger_user_id"), "credit_ledger", ["user_id"], unique=False
    )

    op.create_table(
        "rate_limits",
        sa.Column("bucket", sa.String(length=50), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("bucket", "key", "window_start"),
    )
    op.create_index(
        op.f("ix_rate_limits_window_start"),
        "rate_limits",
        ["window_start"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_rate_limits_window_start"), table_name="rate_limits")
    op.drop_table("rate_limits")
    op.drop_index(op.f("ix_credit_ledger_user_id"), table_name="credit_ledger")
    op.drop_table("credit_ledger")
    op.drop_column("workspaces", "storage_bytes")
    op.drop_column("users", "credit_period_start")
    op.drop_column("users", "credit_balance")
