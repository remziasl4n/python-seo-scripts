"""Drafts written in the content editor.

Revision: 0004
Previous: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(64),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("site", sa.String(100), nullable=False),
        sa.Column("keyword", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("brief_run_id", sa.String(32), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("meta_description", sa.Text(), nullable=False),
        sa.Column("url_slug", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("answers", postgresql.JSONB(), nullable=True),
        sa.Column("answers_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_documents_workspace_id", "documents", ["workspace_id"])
    op.create_index("ix_documents_workspace_updated", "documents", ["workspace_id", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_documents_workspace_updated", "documents")
    op.drop_index("ix_documents_workspace_id", "documents")
    op.drop_table("documents")
