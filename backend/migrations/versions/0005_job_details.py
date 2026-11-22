"""Generation jobs keep what the worker actually used (details) and the model settings they ran with (launch)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("generation_jobs", sa.Column("details", postgresql.JSONB(astext_type=sa.Text())))
    op.add_column("generation_jobs", sa.Column("launch", postgresql.JSONB(astext_type=sa.Text())))


def downgrade():
    op.drop_column("generation_jobs", "launch")
    op.drop_column("generation_jobs", "details")
