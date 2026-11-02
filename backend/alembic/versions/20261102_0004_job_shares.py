"""Thêm job_shares: liên kết chia sẻ transcript chỉ đọc."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_share"
down_revision = "0003_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_shares",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("job_shares")
