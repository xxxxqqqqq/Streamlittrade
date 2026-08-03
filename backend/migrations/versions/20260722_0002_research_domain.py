"""创建策略、数据集、实验和模型表。"""

from alembic import op
import sqlalchemy as sa

revision = "20260722_0002"
down_revision = "20260722_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("strategies",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False, unique=True), sa.Column("description", sa.Text(), nullable=False),
        sa.Column("strategy_type", sa.String(30), nullable=False), sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")))
    op.create_index("ix_strategies_slug", "strategies", ["slug"])
    op.create_table("datasets",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("specification", sa.JSON(), nullable=False), sa.Column("row_count", sa.Integer()), sa.Column("feature_count", sa.Integer()),
        sa.Column("artifact_uri", sa.String(500)), sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")))
    op.create_index("ix_datasets_job_id", "datasets", ["job_id"]); op.create_index("ix_datasets_status", "datasets", ["status"])
    op.create_table("experiments",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("dataset_id", sa.Uuid(), sa.ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("algorithm", sa.String(60), nullable=False), sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON()), sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")))
    op.create_index("ix_experiments_job_id", "experiments", ["job_id"]); op.create_index("ix_experiments_dataset_id", "experiments", ["dataset_id"]); op.create_index("ix_experiments_status", "experiments", ["status"])
    op.create_table("model_versions",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("experiment_id", sa.Uuid(), sa.ForeignKey("experiments.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("algorithm", sa.String(60), nullable=False), sa.Column("artifact_uri", sa.String(500), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False), sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")))
    op.create_index("ix_model_versions_experiment_id", "model_versions", ["experiment_id"])


def downgrade() -> None:
    op.drop_table("model_versions"); op.drop_table("experiments"); op.drop_table("datasets"); op.drop_table("strategies")
