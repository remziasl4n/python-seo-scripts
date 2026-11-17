"""Sites: each workspace's websites, edited in the web app (imported from config/sites/).

Revision: 0002
Previous: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sites",
        sa.Column(
            "workspace_id",
            sa.String(64),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("source_context", sa.Text(), nullable=False),
        sa.Column("central_entity", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("sections", postgresql.JSONB(), nullable=False),
        sa.Column("brand_terms", postgresql.JSONB(), nullable=False),
        sa.Column("competitors", postgresql.JSONB(), nullable=False),
        sa.Column("gsc_property", sa.Text(), nullable=False),
        sa.Column("ga4_property_id", sa.Text(), nullable=False),
        sa.Column("sitemaps", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("sites")
