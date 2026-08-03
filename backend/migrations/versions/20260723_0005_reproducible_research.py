"""Add immutable dataset and model reproducibility snapshots."""

from alembic import op
import sqlalchemy as sa

revision = "20260723_0005"
down_revision = "20260723_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("metadata_snapshot", sa.JSON(), nullable=True))
    op.add_column("experiments", sa.Column("reproducibility", sa.JSON(), nullable=True))
    op.add_column("model_versions", sa.Column("reproducibility", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))


def downgrade() -> None:
    op.drop_column("model_versions", "reproducibility")
    op.drop_column("experiments", "reproducibility")
    op.drop_column("datasets", "metadata_snapshot")
