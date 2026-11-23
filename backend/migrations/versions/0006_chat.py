"""Chat: conversations with a text model, and their messages."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("model_id", sa.String(64), sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("conversations_updated", "conversations", ["updated_at"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("reasoning", sa.Text),
        sa.Column("attachments", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("tool_call_id", sa.String(80)),
        sa.Column("job_id", sa.String(36)),
        sa.Column("status", sa.String(16), nullable=False, server_default="done"),
        sa.Column("error_message", sa.String(2000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "position", name="chat_messages_order"),
    )


def downgrade():
    op.drop_table("chat_messages")
    op.drop_index("conversations_updated", table_name="conversations")
    op.drop_table("conversations")
