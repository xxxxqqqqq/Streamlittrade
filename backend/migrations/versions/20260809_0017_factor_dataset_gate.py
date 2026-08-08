"""Bind formal datasets to a passed factor-research gate."""

from alembic import op
import sqlalchemy as sa


revision = "20260809_0017"
down_revision = "20260807_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("factor_research_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_datasets_factor_research_id",
        "datasets",
        "factor_research_runs",
        ["factor_research_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_datasets_factor_research_id", "datasets", ["factor_research_id"])


def downgrade() -> None:
    op.drop_index("ix_datasets_factor_research_id", table_name="datasets")
    op.drop_constraint("fk_datasets_factor_research_id", "datasets", type_="foreignkey")
    op.drop_column("datasets", "factor_research_id")
