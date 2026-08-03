"""Create the versioned data catalog and feature registry."""

from alembic import op
import sqlalchemy as sa

revision="20260723_0008"; down_revision="20260723_0007"; branch_labels=None; depends_on=None

def upgrade():
    op.create_table("data_sources",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("name",sa.String(120),nullable=False),sa.Column("slug",sa.String(80),nullable=False),sa.Column("provider",sa.String(50),nullable=False),sa.Column("asset_type",sa.String(30),nullable=False),sa.Column("configuration",sa.JSON(),nullable=False),sa.Column("status",sa.String(20),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()")),sa.UniqueConstraint("slug"))
    op.create_index("ix_data_sources_slug","data_sources",["slug"]);op.create_index("ix_data_sources_status","data_sources",["status"])
    op.create_table("data_versions",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("source_id",sa.Uuid(),sa.ForeignKey("data_sources.id",ondelete="RESTRICT")),sa.Column("parent_id",sa.Uuid(),sa.ForeignKey("data_versions.id",ondelete="RESTRICT")),sa.Column("job_id",sa.Uuid(),sa.ForeignKey("jobs.id",ondelete="SET NULL")),sa.Column("layer",sa.String(30),nullable=False),sa.Column("status",sa.String(20),nullable=False),sa.Column("specification",sa.JSON(),nullable=False),sa.Column("artifact_uri",sa.String(500)),sa.Column("content_sha256",sa.String(64)),sa.Column("row_count",sa.Integer()),sa.Column("quality_report",sa.JSON()),sa.Column("lineage",sa.JSON(),nullable=False),sa.Column("error_message",sa.Text()),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()")))
    for c in ("source_id","job_id","layer","status","content_sha256"):op.create_index(f"ix_data_versions_{c}","data_versions",[c])
    op.create_table("feature_definitions",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("name",sa.String(120),nullable=False),sa.Column("slug",sa.String(80),nullable=False),sa.Column("version",sa.Integer(),nullable=False),sa.Column("family",sa.String(50),nullable=False),sa.Column("implementation",sa.String(80),nullable=False),sa.Column("parameters",sa.JSON(),nullable=False),sa.Column("description",sa.Text(),nullable=False),sa.Column("status",sa.String(20),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()")),sa.UniqueConstraint("slug","version",name="uq_feature_slug_version"))
    op.create_index("ix_feature_definitions_slug","feature_definitions",["slug"]);op.create_index("ix_feature_definitions_status","feature_definitions",["status"])
    op.create_table("feature_snapshots",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("data_version_id",sa.Uuid(),sa.ForeignKey("data_versions.id",ondelete="RESTRICT")),sa.Column("job_id",sa.Uuid(),sa.ForeignKey("jobs.id",ondelete="SET NULL")),sa.Column("name",sa.String(120),nullable=False),sa.Column("status",sa.String(20),nullable=False),sa.Column("feature_definition_ids",sa.JSON(),nullable=False),sa.Column("artifact_uri",sa.String(500)),sa.Column("content_sha256",sa.String(64)),sa.Column("row_count",sa.Integer()),sa.Column("profile",sa.JSON()),sa.Column("lineage",sa.JSON(),nullable=False),sa.Column("error_message",sa.Text()),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()")))
    for c in ("data_version_id","job_id","status"):op.create_index(f"ix_feature_snapshots_{c}","feature_snapshots",[c])

def downgrade():
    op.drop_table("feature_snapshots");op.drop_table("feature_definitions");op.drop_table("data_versions");op.drop_table("data_sources")
