"""Station identity and model catalog. No model support is assumed or seeded."""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "station",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("instance_id", sa.String(36), nullable=False),
        sa.CheckConstraint("id = 1", name="station_singleton"),
    )
    op.create_table(
        "models",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("workload", sa.String(40), nullable=False),
    )


def downgrade():
    op.drop_table("models")
    op.drop_table("station")
