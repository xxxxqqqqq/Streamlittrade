"""Add project isolation and durable job outbox."""

from datetime import UTC, datetime
import uuid
from alembic import op
import sqlalchemy as sa

revision="20260723_0009";down_revision="20260723_0008";branch_labels=None;depends_on=None

def upgrade():
    op.create_table("projects",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("owner_id",sa.Uuid(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),sa.Column("name",sa.String(120),nullable=False),sa.Column("slug",sa.String(80),nullable=False,unique=True),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()")))
    op.create_index("ix_projects_owner_id","projects",["owner_id"]);op.create_index("ix_projects_slug","projects",["slug"])
    op.create_table("project_members",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("project_id",sa.Uuid(),sa.ForeignKey("projects.id",ondelete="CASCADE"),nullable=False),sa.Column("user_id",sa.Uuid(),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),sa.Column("role",sa.String(30),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()")),sa.UniqueConstraint("project_id","user_id",name="uq_project_member"))
    op.create_index("ix_project_members_project_id","project_members",["project_id"]);op.create_index("ix_project_members_user_id","project_members",["user_id"])
    op.create_table("auth_sessions",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("user_id",sa.Uuid(),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),sa.Column("token_hash",sa.String(64),nullable=False,unique=True),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),sa.Column("revoked_at",sa.DateTime(timezone=True)),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()")))
    op.create_index("ix_auth_sessions_user_id","auth_sessions",["user_id"]);op.create_index("ix_auth_sessions_token_hash","auth_sessions",["token_hash"])
    op.add_column("jobs",sa.Column("owner_id",sa.Uuid(),sa.ForeignKey("users.id",ondelete="SET NULL")));op.add_column("jobs",sa.Column("project_id",sa.Uuid(),sa.ForeignKey("projects.id",ondelete="CASCADE")));op.add_column("jobs",sa.Column("idempotency_key",sa.String(120),unique=True));op.add_column("jobs",sa.Column("attempt",sa.Integer(),nullable=False,server_default="0"));op.add_column("jobs",sa.Column("max_attempts",sa.Integer(),nullable=False,server_default="3"));op.add_column("jobs",sa.Column("lease_expires_at",sa.DateTime(timezone=True)))
    for c in ("owner_id","project_id"):op.create_index(f"ix_jobs_{c}","jobs",[c])
    for table in ("strategies","datasets","experiments","backtest_runs","data_versions","feature_snapshots"):
        op.add_column(table,sa.Column("project_id",sa.Uuid(),sa.ForeignKey("projects.id",ondelete="CASCADE")));op.create_index(f"ix_{table}_project_id",table,["project_id"])
    bind=op.get_bind();owner=bind.execute(sa.text("select id from users order by created_at limit 1")).scalar()
    if owner:
        pid=uuid.uuid4();bind.execute(sa.text("insert into projects(id,owner_id,name,slug) values(:id,:owner,'默认研究项目','default-research')"),{"id":pid,"owner":owner});bind.execute(sa.text("insert into project_members(id,project_id,user_id,role) values(:id,:pid,:uid,'owner')"),{"id":uuid.uuid4(),"pid":pid,"uid":owner})
        bind.execute(sa.text("update jobs set owner_id=:u,project_id=:p where project_id is null"),{"u":owner,"p":pid})
        for table in ("strategies","datasets","experiments","backtest_runs","data_versions","feature_snapshots"):bind.execute(sa.text(f"update {table} set project_id=:p where project_id is null"),{"p":pid})
    op.create_table("outbox_events",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("job_id",sa.Uuid(),sa.ForeignKey("jobs.id",ondelete="CASCADE"),nullable=False,unique=True),sa.Column("function_path",sa.String(200),nullable=False),sa.Column("status",sa.String(20),nullable=False),sa.Column("attempts",sa.Integer(),nullable=False),sa.Column("available_at",sa.DateTime(timezone=True),nullable=False),sa.Column("dispatched_at",sa.DateTime(timezone=True)),sa.Column("last_error",sa.Text()),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()")))
    op.create_index("ix_outbox_events_job_id","outbox_events",["job_id"]);op.create_index("ix_outbox_events_status","outbox_events",["status"])

def downgrade():
    op.drop_table("outbox_events")
    for table in ("feature_snapshots","data_versions","backtest_runs","experiments","datasets","strategies"):op.drop_column(table,"project_id")
    for c in ("lease_expires_at","max_attempts","attempt","idempotency_key","project_id","owner_id"):op.drop_column("jobs",c)
    op.drop_table("auth_sessions");op.drop_table("project_members");op.drop_table("projects")
