"""Add versioned strategy execution and batch prediction registry."""

from alembic import op
import sqlalchemy as sa


revision = "20260723_0012"
down_revision = "20260723_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategies",
        sa.Column("implementation", sa.String(50), nullable=False, server_default="right_trend"),
    )

    op.add_column("backtest_runs", sa.Column("strategy_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_backtest_runs_strategy_id_strategies",
        "backtest_runs",
        "strategies",
        ["strategy_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_backtest_runs_strategy_id", "backtest_runs", ["strategy_id"])

    op.create_table(
        "prediction_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("model_id", sa.Uuid(), sa.ForeignKey("model_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("feature_snapshot_id", sa.Uuid(), sa.ForeignKey("feature_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("artifact_uri", sa.String(500), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    for column in ("project_id","job_id","model_id","feature_snapshot_id","status"):
        op.create_index(f"ix_prediction_runs_{column}","prediction_runs",[column])


def downgrade() -> None:
    op.drop_table("prediction_runs")
    op.drop_index("ix_backtest_runs_strategy_id",table_name="backtest_runs")
    op.drop_constraint("fk_backtest_runs_strategy_id_strategies","backtest_runs",type_="foreignkey")
    op.drop_column("backtest_runs","strategy_id")
    op.drop_column("strategies","implementation")
