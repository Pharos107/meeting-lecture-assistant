"""Tạo các bảng job, transcript, phiên nghe, và biên bản."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_domain"
down_revision = "0001_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("audio_path", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("vocabulary", sa.Text(), nullable=True),
        sa.Column("num_speakers", sa.Integer(), nullable=True),
        sa.Column("diarization_device", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("source in ('upload', 'live')", name="jobs_source_check"),
        sa.CheckConstraint(
            "status in ('queued', 'capturing', 'preprocessing', 'transcribing', 'diarizing', 'ready', 'failed', 'cancelled')",
            name="jobs_status_check",
        ),
        sa.CheckConstraint(
            "num_speakers is null or (num_speakers between 1 and 20)",
            name="jobs_num_speakers_check",
        ),
        sa.CheckConstraint(
            "diarization_device is null or diarization_device in ('cuda', 'cpu')",
            name="jobs_diarization_device_check",
        ),
    )
    op.execute("create index jobs_user_created_idx on jobs (user_id, created_at desc, id desc)")
    op.create_table(
        "live_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("vocabulary", sa.Text(), nullable=True),
        sa.Column("num_speakers", sa.Integer(), nullable=True),
        sa.Column("pcm_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status in ('capturing', 'stopping', 'finalized', 'failed')",
            name="live_sessions_status_check",
        ),
        sa.CheckConstraint(
            "num_speakers is null or (num_speakers between 1 and 20)",
            name="live_sessions_num_speakers_check",
        ),
    )
    op.create_index("live_sessions_job_idx", "live_sessions", ["job_id"])
    op.create_table(
        "segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pass", sa.SmallInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("text_raw", sa.Text(), nullable=False),
        sa.Column("text_cleaned", sa.Text(), nullable=True),
        sa.Column("text_edited", sa.Text(), nullable=True),
        sa.Column("speaker_label", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.CheckConstraint("pass in (1, 2)", name="segments_pass_check"),
        sa.UniqueConstraint("job_id", "pass", "position", name="segments_job_pass_position_key"),
    )
    op.create_table(
        "words",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("speaker_label", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("segment_id", "position", name="words_segment_position_key"),
    )
    op.create_table(
        "speaker_aliases",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("speaker_label", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.CheckConstraint("source in ('manual', 'voice_profile')", name="speaker_aliases_source_check"),
        sa.PrimaryKeyConstraint("job_id", "speaker_label"),
    )
    op.create_table(
        "job_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("job_id", "seq", name="job_events_job_seq_key"),
    )
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
    op.execute(
        "create index llm_runs_job_task_created_idx on llm_runs (job_id, task, created_at desc)"
    )
    op.create_table(
        "llm_map_shards",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shard_index", sa.Integer(), nullable=False),
        sa.Column("input_start_ms", sa.Integer(), nullable=False),
        sa.Column("input_end_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["llm_runs.id"], ondelete="CASCADE"),
        sa.CheckConstraint("status in ('running', 'done', 'failed')", name="llm_map_shards_status_check"),
        sa.PrimaryKeyConstraint("run_id", "shard_index"),
    )
    op.create_table(
        "media_tokens",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
    )
    op.create_index("media_tokens_job_idx", "media_tokens", ["job_id"])
    op.create_table(
        "ws_tickets",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["live_sessions.id"], ondelete="CASCADE"),
    )
    op.create_index("ws_tickets_session_idx", "ws_tickets", ["session_id"])
    op.create_table(
        "voice_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.BYTEA(), nullable=True),
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column("sample_path", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status in ('processing', 'ready', 'failed')",
            name="voice_profiles_status_check",
        ),
    )
    op.create_index("voice_profiles_user_idx", "voice_profiles", ["user_id"])
    op.create_table(
        "highlights",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="CASCADE"),
    )
    op.create_index("highlights_job_idx", "highlights", ["job_id", "created_at"])
    op.create_table(
        "action_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("owner", sa.Text(), nullable=False, server_default=""),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("deadline", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="SET NULL"),
        sa.CheckConstraint("source in ('manual')", name="action_items_source_check"),
    )
    op.create_index("action_items_job_idx", "action_items", ["job_id", "created_at"])


def downgrade() -> None:
    op.drop_index("action_items_job_idx", table_name="action_items")
    op.drop_table("action_items")
    op.drop_index("highlights_job_idx", table_name="highlights")
    op.drop_table("highlights")
    op.drop_index("voice_profiles_user_idx", table_name="voice_profiles")
    op.drop_table("voice_profiles")
    op.drop_index("ws_tickets_session_idx", table_name="ws_tickets")
    op.drop_table("ws_tickets")
    op.drop_index("media_tokens_job_idx", table_name="media_tokens")
    op.drop_table("media_tokens")
    op.drop_table("llm_map_shards")
    op.drop_index("llm_runs_job_task_created_idx", table_name="llm_runs")
    op.drop_table("llm_runs")
    op.drop_table("job_events")
    op.drop_table("speaker_aliases")
    op.drop_table("words")
    op.drop_table("segments")
    op.drop_index("live_sessions_job_idx", table_name="live_sessions")
    op.drop_table("live_sessions")
    op.drop_index("jobs_user_created_idx", table_name="jobs")
    op.drop_table("jobs")
