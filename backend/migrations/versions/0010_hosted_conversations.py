"""A conversation may be with a hosted model ("<provider>:<model>"), which has no row in `models`: drop the foreign key and make room."""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("conversations_model_id_fkey", "conversations", type_="foreignkey")
    op.alter_column("conversations", "model_id", existing_type=sa.String(64), type_=sa.String(160), existing_nullable=False)


def downgrade():
    op.execute("DELETE FROM conversations WHERE model_id NOT IN (SELECT id FROM models)")
    op.alter_column("conversations", "model_id", existing_type=sa.String(160), type_=sa.String(64), existing_nullable=False)
    op.create_foreign_key("conversations_model_id_fkey", "conversations", "models", ["model_id"], ["id"], ondelete="CASCADE")
