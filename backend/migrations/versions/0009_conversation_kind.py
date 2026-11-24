"""Conversations have a kind: "chat" (the Chat page) or "assistant" (the help bubble on every page)."""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("conversations", sa.Column("kind", sa.String(20), nullable=False, server_default="chat"))


def downgrade():
    op.drop_column("conversations", "kind")
