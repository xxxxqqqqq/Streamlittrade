"""Resolve and authorize the active project for a request."""

from dataclasses import dataclass
from uuid import UUID
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.security import get_current_user
from backend.app.db.session import get_db_session
from backend.app.models.identity import Project, ProjectMember, User


@dataclass(frozen=True)
class ProjectContext:
    project: Project
    membership: ProjectMember
    user: User


async def get_project_context(
    x_project_id: UUID | None = Header(default=None, alias="X-Project-ID"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectContext:
    query = select(ProjectMember).where(ProjectMember.user_id == user.id)
    if x_project_id:
        query = query.where(ProjectMember.project_id == x_project_id)
    membership = await session.scalar(query.order_by(ProjectMember.created_at))
    if membership is None:
        raise HTTPException(403, "No accessible project was found")
    project = await session.get(Project, membership.project_id)
    if project is None:
        raise HTTPException(403, "Project is unavailable")
    return ProjectContext(project=project, membership=membership, user=user)


def require_project_admin(context: ProjectContext = Depends(get_project_context)) -> ProjectContext:
    if context.membership.role not in {"owner", "admin"}:
        raise HTTPException(403, "Project administrator permission required")
    return context
