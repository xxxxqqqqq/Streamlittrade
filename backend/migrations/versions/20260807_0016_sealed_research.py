"""Add one-time sealed holdout evaluations."""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0016"
down_revision = "20260731_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sealed_evaluations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), sa.ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("model_id", sa.Uuid(), sa.ForeignKey("model_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("artifact_uri", sa.String(500), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("dataset_id", name="uq_sealed_evaluation_dataset"),
        sa.UniqueConstraint("model_id", name="uq_sealed_evaluation_model"),
        sa.UniqueConstraint("job_id", name="uq_sealed_evaluation_job"),
    )
    for column in ("project_id", "dataset_id", "model_id", "job_id", "status"):
        op.create_index(f"ix_sealed_evaluations_{column}", "sealed_evaluations", [column])


def downgrade() -> None:
    op.drop_table("sealed_evaluations")
