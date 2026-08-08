"""Add auditable model-to-paper automation schedules and runs."""

from alembic import op
import sqlalchemy as sa

revision = "20260809_0018"
down_revision = "20260809_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_automation_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("algorithm", sa.String(60), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("top_n", sa.Integer(), nullable=False),
        sa.Column("probability_threshold", sa.Float(), nullable=False),
        sa.Column("gross_exposure", sa.Float(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_job_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["account_id"], ["paper_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (("ix_paper_automation_schedules_project_id", ["project_id"]), ("ix_paper_automation_schedules_account_id", ["account_id"]), ("ix_paper_automation_schedules_algorithm", ["algorithm"]), ("ix_paper_automation_schedules_enabled", ["enabled"]), ("ix_paper_automation_schedules_next_run_at", ["next_run_at"])):
        op.create_index(name, "paper_automation_schedules", columns)
    op.create_table(
        "paper_automation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("feature_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=True),
        sa.Column("intended_trade_date", sa.Date(), nullable=True),
        sa.Column("signals", sa.JSON(), nullable=True),
        sa.Column("targets", sa.JSON(), nullable=True),
        sa.Column("order_ids", sa.JSON(), nullable=False),
        sa.Column("lineage", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["schedule_id"], ["paper_automation_schedules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["paper_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_id"], ["model_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["feature_snapshot_id"], ["feature_snapshots.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
        sa.UniqueConstraint("schedule_id", "feature_snapshot_id", name="uq_paper_automation_schedule_snapshot"),
    )
    for name, columns in (("ix_paper_automation_runs_project_id", ["project_id"]), ("ix_paper_automation_runs_schedule_id", ["schedule_id"]), ("ix_paper_automation_runs_status", ["status"])):
        op.create_index(name, "paper_automation_runs", columns)


def downgrade() -> None:
    op.drop_table("paper_automation_runs")
    op.drop_table("paper_automation_schedules")
