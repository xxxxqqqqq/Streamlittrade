"""Add disabled-by-default broker boundary and paper stability evaluations."""

from alembic import op
import sqlalchemy as sa

revision = "20260809_0019"
down_revision = "20260809_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broker_connections",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("paper_account_id", sa.Uuid(), nullable=False), sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("environment", sa.String(20), nullable=False), sa.Column("credential_secret_ref", sa.String(160), nullable=True),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True), sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paper_account_id"], ["paper_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("project_id", "paper_account_id", "provider", name="uq_broker_connection_scope"),
    )
    for name, columns in (("ix_broker_connections_project_id", ["project_id"]), ("ix_broker_connections_paper_account_id", ["paper_account_id"]), ("ix_broker_connections_status", ["status"])):
        op.create_index(name, "broker_connections", columns)
    op.create_table(
        "live_readiness_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False), sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False), sa.Column("policy_version", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["broker_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (("ix_live_readiness_evaluations_project_id", ["project_id"]), ("ix_live_readiness_evaluations_connection_id", ["connection_id"]), ("ix_live_readiness_evaluations_eligible", ["eligible"])):
        op.create_index(name, "live_readiness_evaluations", columns)


def downgrade() -> None:
    op.drop_table("live_readiness_evaluations")
    op.drop_table("broker_connections")
