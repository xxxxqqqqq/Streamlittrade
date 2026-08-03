"""Add model lineage and portfolio-construction metadata to backtests."""

from alembic import op
import sqlalchemy as sa


revision = "20260724_0014"
down_revision = "20260723_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "backtest_runs",
        sa.Column(
            "model_id",
            sa.Uuid(),
            sa.ForeignKey("model_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "backtest_runs",
        sa.Column(
            "signal_source",
            sa.String(30),
            nullable=False,
            server_default="strategy",
        ),
    )
    op.add_column(
        "backtest_runs",
        sa.Column(
            "portfolio_construction",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.create_index("ix_backtest_runs_model_id", "backtest_runs", ["model_id"])
    op.create_index(
        "ix_backtest_runs_signal_source", "backtest_runs", ["signal_source"]
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_runs_signal_source", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_model_id", table_name="backtest_runs")
    op.drop_column("backtest_runs", "portfolio_construction")
    op.drop_column("backtest_runs", "signal_source")
    op.drop_column("backtest_runs", "model_id")
