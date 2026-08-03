"""创建完全隔离的模拟交易账本。

Revision ID: 20260723_0004
Revises: 20260723_0003
"""

from alembic import op
import sqlalchemy as sa

revision="20260723_0004";down_revision="20260723_0003";branch_labels=None;depends_on=None


def upgrade() -> None:
    op.create_table("paper_accounts",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("user_id",sa.Uuid(),sa.ForeignKey("users.id"),nullable=False),sa.Column("name",sa.String(100),nullable=False),sa.Column("initial_cash",sa.Numeric(18,2),nullable=False),sa.Column("cash",sa.Numeric(18,2),nullable=False),sa.Column("status",sa.String(20),nullable=False),sa.Column("risk_limits",sa.JSON(),nullable=False),sa.Column("last_settlement_date",sa.Date(),nullable=True),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False));op.create_index("ix_paper_accounts_user_id","paper_accounts",["user_id"])
    op.create_table("paper_positions",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("account_id",sa.Uuid(),sa.ForeignKey("paper_accounts.id",ondelete="CASCADE"),nullable=False),sa.Column("symbol",sa.String(20),nullable=False),sa.Column("quantity",sa.Integer(),nullable=False),sa.Column("sellable_quantity",sa.Integer(),nullable=False),sa.Column("average_cost",sa.Numeric(18,4),nullable=False),sa.Column("last_price",sa.Numeric(18,4),nullable=False),sa.Column("last_buy_date",sa.Date(),nullable=True),sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),sa.UniqueConstraint("account_id","symbol",name="uq_paper_position_account_symbol"));op.create_index("ix_paper_positions_account_id","paper_positions",["account_id"])
    op.create_table("paper_orders",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("account_id",sa.Uuid(),sa.ForeignKey("paper_accounts.id",ondelete="CASCADE"),nullable=False),sa.Column("symbol",sa.String(20),nullable=False),sa.Column("side",sa.String(10),nullable=False),sa.Column("quantity",sa.Integer(),nullable=False),sa.Column("snapshot_price",sa.Numeric(18,4),nullable=False),sa.Column("status",sa.String(20),nullable=False),sa.Column("trade_date",sa.Date(),nullable=False),sa.Column("source",sa.String(30),nullable=False),sa.Column("message",sa.String(500),nullable=True),sa.Column("submitted_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False));op.create_index("ix_paper_orders_account_id","paper_orders",["account_id"])
    op.create_table("paper_fills",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("order_id",sa.Uuid(),sa.ForeignKey("paper_orders.id",ondelete="CASCADE"),nullable=False,unique=True),sa.Column("quantity",sa.Integer(),nullable=False),sa.Column("price",sa.Numeric(18,4),nullable=False),sa.Column("gross_amount",sa.Numeric(18,2),nullable=False),sa.Column("commission",sa.Numeric(18,2),nullable=False),sa.Column("stamp_tax",sa.Numeric(18,2),nullable=False),sa.Column("transfer_fee",sa.Numeric(18,2),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))


def downgrade() -> None:
    op.drop_table("paper_fills");op.drop_table("paper_orders");op.drop_table("paper_positions");op.drop_table("paper_accounts")
