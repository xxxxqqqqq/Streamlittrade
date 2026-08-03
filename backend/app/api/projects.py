"""Project creation, membership and active-scope discovery."""

from uuid import uuid4
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.projects import ProjectContext,get_project_context,require_project_admin
from backend.app.core.security import get_current_user
from backend.app.db.session import get_db_session
from backend.app.models.identity import AuditLog,Project,ProjectMember,User
from backend.app.schemas.projects import MemberCreate,MemberDetail,MemberRead,MemberUpdate,ProjectCreate,ProjectRead

router=APIRouter(prefix="/projects",tags=["projects"])

@router.get("",response_model=list[ProjectRead])
async def list_projects(user:User=Depends(get_current_user),session:AsyncSession=Depends(get_db_session)):
    rows=(await session.execute(select(Project,ProjectMember.role).join(ProjectMember,ProjectMember.project_id==Project.id).where(ProjectMember.user_id==user.id).order_by(Project.created_at))).all()
    return [ProjectRead.model_validate(project).model_copy(update={"member_role":role}) for project,role in rows]

@router.post("",response_model=ProjectRead,status_code=201)
async def create_project(body:ProjectCreate,user:User=Depends(get_current_user),session:AsyncSession=Depends(get_db_session)):
    if await session.scalar(select(Project).where(Project.slug==body.slug)):raise HTTPException(409,"Project slug already exists")
    project=Project(id=uuid4(),owner_id=user.id,**body.model_dump());member=ProjectMember(project_id=project.id,user_id=user.id,role="owner")
    session.add(project);await session.flush();session.add_all([member,AuditLog(actor_id=user.id,action="project.created",resource_type="project",resource_id=str(project.id))]);await session.commit();await session.refresh(project)
    return ProjectRead.model_validate(project).model_copy(update={"member_role":"owner"})

@router.get("/active",response_model=ProjectRead)
async def active(context:ProjectContext=Depends(get_project_context)):
    return ProjectRead.model_validate(context.project).model_copy(update={"member_role":context.membership.role})

@router.post("/{project_id}/members",response_model=MemberRead,status_code=201)
async def add_member(project_id,body:MemberCreate,context:ProjectContext=Depends(require_project_admin),session:AsyncSession=Depends(get_db_session)):
    if str(context.project.id)!=str(project_id):raise HTTPException(403,"Project scope mismatch")
    if not await session.get(User,body.user_id):raise HTTPException(404,"User not found")
    if await session.scalar(select(ProjectMember).where(ProjectMember.project_id==context.project.id,ProjectMember.user_id==body.user_id)):raise HTTPException(409,"User is already a member")
    member=ProjectMember(project_id=context.project.id,**body.model_dump());session.add(member);await session.commit();await session.refresh(member);return member

@router.get("/{project_id}/members",response_model=list[MemberDetail])
async def list_members(project_id,context:ProjectContext=Depends(get_project_context),session:AsyncSession=Depends(get_db_session)):
    if str(context.project.id)!=str(project_id):raise HTTPException(403,"Project scope mismatch")
    rows=(await session.execute(select(ProjectMember,User).join(User,User.id==ProjectMember.user_id).where(ProjectMember.project_id==context.project.id).order_by(ProjectMember.created_at))).all()
    return [
        MemberDetail(
            **MemberRead.model_validate(member).model_dump(),
            email=user.email,
            display_name=user.display_name,
        )
        for member,user in rows
    ]

@router.patch("/{project_id}/members/{member_id}",response_model=MemberRead)
async def update_member(project_id,member_id,body:MemberUpdate,context:ProjectContext=Depends(require_project_admin),session:AsyncSession=Depends(get_db_session)):
    if str(context.project.id)!=str(project_id):raise HTTPException(403,"Project scope mismatch")
    member=await session.scalar(select(ProjectMember).where(ProjectMember.id==member_id,ProjectMember.project_id==context.project.id))
    if member is None:raise HTTPException(404,"Member not found")
    if member.user_id==context.project.owner_id:raise HTTPException(409,"不能修改项目所有者角色")
    previous=member.role;member.role=body.role
    session.add(AuditLog(actor_id=context.user.id,action="project.member_role_changed",resource_type="project_member",resource_id=str(member.id),details={"from":previous,"to":body.role,"project_id":str(context.project.id)}))
    await session.commit();await session.refresh(member);return member

@router.delete("/{project_id}/members/{member_id}",status_code=204)
async def remove_member(project_id,member_id,context:ProjectContext=Depends(require_project_admin),session:AsyncSession=Depends(get_db_session)):
    if str(context.project.id)!=str(project_id):raise HTTPException(403,"Project scope mismatch")
    member=await session.scalar(select(ProjectMember).where(ProjectMember.id==member_id,ProjectMember.project_id==context.project.id))
    if member is None:raise HTTPException(404,"Member not found")
    if member.user_id==context.project.owner_id:raise HTTPException(409,"不能移除项目所有者")
    session.add(AuditLog(actor_id=context.user.id,action="project.member_removed",resource_type="project_member",resource_id=str(member.id),details={"project_id":str(context.project.id),"user_id":str(member.user_id)}))
    await session.delete(member);await session.commit()
