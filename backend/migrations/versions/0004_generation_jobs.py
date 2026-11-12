"""Generation jobs: what was asked for, its status, and the files it produced."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_id", sa.String(64), sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("load_operation_id", sa.String(36)),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.String(200)),
        sa.Column("outputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("error_message", sa.String(2000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_generation_jobs_created", "generation_jobs", ["created_at"])


def downgrade():
    op.drop_index("ix_generation_jobs_created", table_name="generation_jobs")
    op.drop_table("generation_jobs")
