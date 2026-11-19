"""Runs can have a written report (e.g. a content plan) next to their results table.

Revision: 0003
Previous: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("report", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "report")
