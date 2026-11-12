"""Record the validated launch settings of real runtime loads."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("operations", sa.Column("launch", postgresql.JSONB(astext_type=sa.Text())))


def downgrade():
    op.drop_column("operations", "launch")
