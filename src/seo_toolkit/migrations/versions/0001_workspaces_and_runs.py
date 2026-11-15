"""Workspaces and runs, with the local workspace every local run belongs to.

Revision: 0001
Previous:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.execute("INSERT INTO workspaces (id, name) VALUES ('local', 'Local')")

    op.create_table(
        "runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(64),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_id", sa.String(100), nullable=False),
        sa.Column("tool_title", sa.String(200), nullable=False),
        sa.Column("site", sa.String(100), nullable=False),
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        sa.Column("refresh", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("notes", postgresql.JSONB(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("output", sa.Text(), nullable=True),
    )
    op.create_index("ix_runs_workspace_id", "runs", ["workspace_id"])
    op.create_index("ix_runs_tool_id", "runs", ["tool_id"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_workspace_created", "runs", ["workspace_id", "created_at"])


def downgrade() -> None:
    op.drop_table("runs")
    op.drop_table("workspaces")
