"""Chuyển LLM sang hỏi đáp: thêm chat_messages, bỏ chuẩn hóa và biên bản."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_chat"
down_revision = "0002_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("llm_map_shards")
    op.drop_index("llm_runs_job_task_created_idx", table_name="llm_runs")
    op.drop_table("llm_runs")
    op.drop_column("segments", "text_cleaned")

    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.CheckConstraint("role in ('user', 'assistant')", name="chat_messages_role_check"),
        sa.CheckConstraint("status in ('streaming', 'done', 'stopped', 'failed')", name="chat_messages_status_check"),
    )
    op.create_index("chat_messages_job_created_idx", "chat_messages", ["job_id", "created_at"])
    op.execute(
        "create unique index chat_messages_one_streaming_idx on chat_messages (job_id) where status = 'streaming'"
    )


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.add_column("segments", sa.Column("text_cleaned", sa.Text(), nullable=True))
    op.create_table(
        "llm_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("template", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.CheckConstraint("task in ('clean', 'summarize')", name="llm_runs_task_check"),
        sa.CheckConstraint(
            "template is null or template in ('meeting', 'lecture')",
            name="llm_runs_template_check",
        ),
        sa.CheckConstraint("status in ('running', 'done', 'failed')", name="llm_runs_status_check"),
        sa.CheckConstraint("task = 'clean' or template is not null", name="llm_runs_template_required_check"),
    )
    op.execute("create index llm_runs_job_task_created_idx on llm_runs (job_id, task, created_at desc)")
    op.create_table(
        "llm_map_shards",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shard_index", sa.Integer(), nullable=False),
        sa.Column("input_start_ms", sa.Integer(), nullable=False),
        sa.Column("input_end_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("run_id", "shard_index"),
        sa.ForeignKeyConstraint(["run_id"], ["llm_runs.id"], ondelete="CASCADE"),
        sa.CheckConstraint("status in ('running', 'done', 'failed')", name="llm_map_shards_status_check"),
    )
