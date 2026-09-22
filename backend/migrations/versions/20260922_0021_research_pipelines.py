"""Add server-orchestrated one-click research pipelines."""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0021"
down_revision = "20260825_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "research_pipelines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("current_step", sa.String(30), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("current_job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_research_pipelines_project_id", "research_pipelines", ["project_id"])
    op.create_index("ix_research_pipelines_owner_id", "research_pipelines", ["owner_id"])
    op.create_index("ix_research_pipelines_status", "research_pipelines", ["status"])
    op.create_index("ix_research_pipelines_current_job_id", "research_pipelines", ["current_job_id"])


def downgrade():
    op.drop_index("ix_research_pipelines_current_job_id", table_name="research_pipelines")
    op.drop_index("ix_research_pipelines_status", table_name="research_pipelines")
    op.drop_index("ix_research_pipelines_owner_id", table_name="research_pipelines")
    op.drop_index("ix_research_pipelines_project_id", table_name="research_pipelines")
    op.drop_table("research_pipelines")
