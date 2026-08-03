"""Add portfolio backtest type and persisted data-quality report."""

from alembic import op
import sqlalchemy as sa

revision = "20260723_0006"
down_revision = "20260723_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backtest_runs", sa.Column("run_type", sa.String(20), nullable=False, server_default="single"))
    op.add_column("backtest_runs", sa.Column("data_quality", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("backtest_runs", "data_quality")
    op.drop_column("backtest_runs", "run_type")
