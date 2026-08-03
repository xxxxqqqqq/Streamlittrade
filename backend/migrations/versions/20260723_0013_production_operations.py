"""Add prediction schedules, drift monitoring, and persistent alerts."""

from alembic import op
import sqlalchemy as sa


revision = "20260723_0013"
down_revision = "20260723_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prediction_schedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("algorithm", sa.String(60), nullable=False),
        sa.Column(
            "feature_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("feature_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    for column in (
        "project_id",
        "owner_id",
        "algorithm",
        "feature_snapshot_id",
        "enabled",
        "next_run_at",
    ):
        op.create_index(
            f"ix_prediction_schedules_{column}", "prediction_schedules", [column]
        )

    op.create_table(
        "drift_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "model_id",
            sa.Uuid(),
            sa.ForeignKey("model_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "baseline_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("feature_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "current_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("feature_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("alert_level", sa.String(20), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    for column in ("project_id", "job_id", "model_id", "status", "alert_level"):
        op.create_index(f"ix_drift_runs_{column}", "drift_runs", [column])

    op.create_table(
        "alert_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "drift_run_id",
            sa.Uuid(),
            sa.ForeignKey("drift_runs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "acknowledged_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    for column in (
        "project_id",
        "drift_run_id",
        "code",
        "severity",
        "status",
    ):
        op.create_index(f"ix_alert_events_{column}", "alert_events", [column])


def downgrade() -> None:
    op.drop_table("alert_events")
    op.drop_table("drift_runs")
    op.drop_table("prediction_schedules")

