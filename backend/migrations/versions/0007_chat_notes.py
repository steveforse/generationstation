"""Chat tool results keep a one-line note for the chat (the model reads the full text)."""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_messages", sa.Column("note", sa.String(500)))


def downgrade():
    op.drop_column("chat_messages", "note")
