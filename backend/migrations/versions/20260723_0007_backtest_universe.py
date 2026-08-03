"""Expand the backtest symbol field for portfolio universes."""

from alembic import op
import sqlalchemy as sa

revision = "20260723_0007"
down_revision = "20260723_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("backtest_runs", "symbol", type_=sa.String(1000), existing_type=sa.String(20))


def downgrade() -> None:
    op.alter_column("backtest_runs", "symbol", type_=sa.String(20), existing_type=sa.String(1000))
