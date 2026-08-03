"""Harden project isolation for paper accounts, jobs and strategy versions."""

from alembic import op
import sqlalchemy as sa


revision = "20260723_0010"
down_revision = "20260723_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 模拟账户从“创建者私有”升级为项目资源；创建者仍保留在 user_id。
    op.add_column("paper_accounts", sa.Column("project_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_paper_accounts_project_id_projects",
        "paper_accounts",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_paper_accounts_project_id", "paper_accounts", ["project_id"])

    bind = op.get_bind()
    # 极端情况下旧账户创建者还没有项目，先为其建立迁移专用默认项目。
    bind.execute(
        sa.text(
            """
            INSERT INTO projects (id, owner_id, name, slug, created_at)
            SELECT gen_random_uuid(), owners.user_id, '默认研究项目',
                   'paper-migrated-' || left(replace(owners.user_id::text, '-', ''), 16),
                   now()
            FROM (SELECT DISTINCT user_id FROM paper_accounts) AS owners
            WHERE NOT EXISTS (
                SELECT 1 FROM project_members pm WHERE pm.user_id = owners.user_id
            )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO project_members (id, project_id, user_id, role, created_at)
            SELECT gen_random_uuid(), p.id, p.owner_id, 'owner', now()
            FROM projects p
            WHERE p.slug LIKE 'paper-migrated-%'
              AND NOT EXISTS (
                  SELECT 1 FROM project_members pm
                  WHERE pm.project_id = p.id AND pm.user_id = p.owner_id
              )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE paper_accounts AS account
            SET project_id = (
                SELECT pm.project_id
                FROM project_members pm
                WHERE pm.user_id = account.user_id
                ORDER BY pm.created_at, pm.id
                LIMIT 1
            )
            WHERE account.project_id IS NULL
            """
        )
    )
    remaining = bind.execute(
        sa.text("SELECT count(*) FROM paper_accounts WHERE project_id IS NULL")
    ).scalar_one()
    if remaining:
        raise RuntimeError("Cannot migrate paper accounts without an accessible project")
    op.alter_column("paper_accounts", "project_id", nullable=False)

    # slug 只在项目和版本组合内唯一，不再占用全平台命名空间。
    op.drop_constraint("strategies_slug_key", "strategies", type_="unique")
    op.create_unique_constraint(
        "uq_strategy_project_slug_version",
        "strategies",
        ["project_id", "slug", "version"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_strategy_project_slug_version", "strategies", type_="unique")
    op.create_unique_constraint("strategies_slug_key", "strategies", ["slug"])
    op.drop_index("ix_paper_accounts_project_id", table_name="paper_accounts")
    op.drop_constraint(
        "fk_paper_accounts_project_id_projects",
        "paper_accounts",
        type_="foreignkey",
    )
    op.drop_column("paper_accounts", "project_id")
