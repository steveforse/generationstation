"""Persist simulation profiles, lifecycle state, operations, and reservations."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_id", sa.String(64), sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("workload", sa.String(40), nullable=False),
        sa.Column("ram_peak_bytes", sa.BigInteger(), nullable=False),
        sa.Column("gpu_vram_bytes_by_id", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("ram_peak_bytes > 0", name="profile_ram_positive"),
        sa.CheckConstraint("mode = 'simulation'", name="profile_simulation_only"),
    )
    op.create_table(
        "model_runtime",
        sa.Column("model_id", sa.String(64), sa.ForeignKey("models.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("state", sa.String(24), nullable=False, server_default="unloaded"),
        sa.Column("active_operation_id", sa.String(36)),
        sa.Column("reservation_operation_id", sa.String(36)),
        sa.Column("active_worker_id", sa.String(80)),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("last_error_message", sa.String(500)),
    )
    op.execute("INSERT INTO model_runtime (model_id, state) SELECT id, 'unloaded' FROM models")
    op.create_table(
        "operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_id", sa.String(64), sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("model_profiles.id", ondelete="SET NULL")),
        sa.Column("profile_revision", sa.Integer()),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("parent_operation_id", sa.String(36)),
        sa.Column("reservation_operation_id", sa.String(36)),
        sa.Column("worker_id", sa.String(80)),
        sa.Column("refusal", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_operations_model_created", "operations", ["model_id", "created_at"])
    op.create_table(
        "capacity_reservations",
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("operations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("model_id", sa.String(64), sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ram_bytes", sa.BigInteger(), nullable=False),
        sa.Column("gpu_vram_bytes_by_id", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_reservations_active", "capacity_reservations", ["active"])


def downgrade():
    op.drop_index("ix_reservations_active", table_name="capacity_reservations")
    op.drop_table("capacity_reservations")
    op.drop_index("ix_operations_model_created", table_name="operations")
    op.drop_table("operations")
    op.drop_table("model_runtime")
    op.drop_table("model_profiles")
