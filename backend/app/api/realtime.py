"""认证后的实时任务状态 WebSocket。"""

import asyncio
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jwt import InvalidTokenError
from sqlalchemy import select

from backend.app.core.security import decode_access_token
from backend.app.db.session import AsyncSessionFactory
from backend.app.models.identity import ProjectMember, User
from backend.app.models.job import Job
from backend.app.schemas.backtest import JobRead


router = APIRouter(tags=["realtime"])


@router.websocket("/ws/jobs")
async def jobs_stream(websocket: WebSocket, token: str, project_id: UUID | None = None) -> None:
    """每秒推送当前用户有权访问的项目任务。"""
    try:
        user_id = decode_access_token(token)
    except (InvalidTokenError, KeyError, ValueError):
        await websocket.close(code=4401)
        return
    async with AsyncSessionFactory() as session:
        user = await session.get(User, user_id)
        if user is None or not user.is_active:
            await websocket.close(code=4401)
            return
        membership_query = select(ProjectMember).where(ProjectMember.user_id == user.id)
        if project_id is not None:
            membership_query = membership_query.where(ProjectMember.project_id == project_id)
        membership = await session.scalar(membership_query.order_by(ProjectMember.created_at))
        if membership is None:
            await websocket.close(code=4403)
            return
        active_project_id = membership.project_id
    await websocket.accept()
    try:
        while True:
            async with AsyncSessionFactory() as session:
                jobs = (
                    await session.scalars(
                        select(Job)
                        .where(Job.project_id == active_project_id)
                        .order_by(Job.created_at.desc())
                        .limit(100)
                    )
                ).all()
                payload = [JobRead.model_validate(item).model_dump(mode="json") for item in jobs]
            await websocket.send_json(payload)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
