"""Add persisted factor research and screening runs."""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0015"
down_revision = "20260724_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "factor_research_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("feature_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("parameters", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column(
            "selected_feature_slugs",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_factor_research_runs_project_id", "factor_research_runs", ["project_id"])
    op.create_index("ix_factor_research_runs_snapshot_id", "factor_research_runs", ["snapshot_id"])
    op.create_index("ix_factor_research_runs_job_id", "factor_research_runs", ["job_id"])
    op.create_index("ix_factor_research_runs_status", "factor_research_runs", ["status"])


def downgrade() -> None:
    op.drop_table("factor_research_runs")
