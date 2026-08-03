"""Link formal data assets to datasets, models and backtests."""

from alembic import op
import sqlalchemy as sa


revision = "20260723_0011"
down_revision = "20260723_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("feature_snapshot_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_datasets_feature_snapshot_id_feature_snapshots",
        "datasets",
        "feature_snapshots",
        ["feature_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_datasets_feature_snapshot_id", "datasets", ["feature_snapshot_id"])

    op.add_column("model_versions", sa.Column("prediction_artifact_uri", sa.String(500), nullable=True))

    op.add_column("backtest_runs", sa.Column("data_version_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_backtest_runs_data_version_id_data_versions",
        "backtest_runs",
        "data_versions",
        ["data_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_backtest_runs_data_version_id", "backtest_runs", ["data_version_id"])


def downgrade() -> None:
    op.drop_index("ix_backtest_runs_data_version_id", table_name="backtest_runs")
    op.drop_constraint(
        "fk_backtest_runs_data_version_id_data_versions",
        "backtest_runs",
        type_="foreignkey",
    )
    op.drop_column("backtest_runs", "data_version_id")
    op.drop_column("model_versions", "prediction_artifact_uri")
    op.drop_index("ix_datasets_feature_snapshot_id", table_name="datasets")
    op.drop_constraint(
        "fk_datasets_feature_snapshot_id_feature_snapshots",
        "datasets",
        type_="foreignkey",
    )
    op.drop_column("datasets", "feature_snapshot_id")
