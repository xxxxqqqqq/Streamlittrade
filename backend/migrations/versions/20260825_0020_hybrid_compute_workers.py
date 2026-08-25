"""Add explicit queue routing and compute worker observability."""

from alembic import op
import sqlalchemy as sa


revision = "20260825_0020"
down_revision = "20260809_0019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("queue_name", sa.String(80), nullable=True))
    op.add_column("jobs", sa.Column("worker_name", sa.String(120), nullable=True))
    op.add_column("jobs", sa.Column("worker_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_jobs_queue_name", "jobs", ["queue_name"])
    op.create_index("ix_jobs_worker_name", "jobs", ["worker_name"])
    op.add_column("outbox_events", sa.Column("queue_name", sa.String(80), nullable=True))


def downgrade():
    op.drop_column("outbox_events", "queue_name")
    op.drop_index("ix_jobs_worker_name", table_name="jobs")
    op.drop_index("ix_jobs_queue_name", table_name="jobs")
    op.drop_column("jobs", "worker_heartbeat_at")
    op.drop_column("jobs", "worker_name")
    op.drop_column("jobs", "queue_name")
