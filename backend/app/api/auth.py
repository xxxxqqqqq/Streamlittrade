"""登录、当前用户和管理员审计接口。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import create_access_token, create_refresh_token, get_current_user, hash_password, hash_refresh_token, require_admin, verify_password
from backend.app.db.session import get_db_session
from backend.app.models.identity import AuditLog, AuthSession, User
from backend.app.schemas.auth import AuditRead, LoginRequest, RefreshRequest, TokenResponse, UserCreate, UserRead, UserUpdate
from datetime import UTC, datetime, timedelta
from backend.app.core.config import get_settings


router = APIRouter(tags=["identity"])


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    user = await session.scalar(select(User).where(User.email == body.email.lower().strip()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    token, expires = create_access_token(user)
    refresh, refresh_hash = create_refresh_token()
    session.add(AuthSession(user_id=user.id, token_hash=refresh_hash, expires_at=datetime.now(UTC)+timedelta(days=get_settings().refresh_token_days)))
    session.add(AuditLog(actor_id=user.id, action="auth.login", resource_type="user", resource_id=str(user.id)))
    await session.commit()
    return TokenResponse(access_token=token, refresh_token=refresh, expires_in=expires, user=UserRead.model_validate(user))


@router.post("/auth/refresh",response_model=TokenResponse)
async def refresh(body:RefreshRequest,session:AsyncSession=Depends(get_db_session)):
    item=await session.scalar(select(AuthSession).where(AuthSession.token_hash==hash_refresh_token(body.refresh_token)))
    if item is None or item.revoked_at is not None or item.expires_at<=datetime.now(UTC):raise HTTPException(401,"Refresh session is invalid")
    user=await session.get(User,item.user_id)
    if user is None or not user.is_active:raise HTTPException(401,"User is inactive")
    item.revoked_at=datetime.now(UTC);new_refresh,new_hash=create_refresh_token();session.add(AuthSession(user_id=user.id,token_hash=new_hash,expires_at=datetime.now(UTC)+timedelta(days=get_settings().refresh_token_days)))
    token,expires=create_access_token(user);session.add(AuditLog(actor_id=user.id,action="auth.refresh",resource_type="session",resource_id=str(item.id)));await session.commit()
    return TokenResponse(access_token=token,refresh_token=new_refresh,expires_in=expires,user=UserRead.model_validate(user))


@router.post("/auth/logout",status_code=204)
async def logout(body:RefreshRequest,session:AsyncSession=Depends(get_db_session)):
    item=await session.scalar(select(AuthSession).where(AuthSession.token_hash==hash_refresh_token(body.refresh_token)))
    if item and item.revoked_at is None:item.revoked_at=datetime.now(UTC);await session.commit()


@router.get("/auth/me", response_model=UserRead)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/users",response_model=UserRead,status_code=201)
async def create_user(body:UserCreate,admin:User=Depends(require_admin),session:AsyncSession=Depends(get_db_session)):
    email=body.email.lower().strip()
    if await session.scalar(select(User).where(User.email==email)):raise HTTPException(409,"Email already exists")
    user=User(email=email,display_name=body.display_name,password_hash=hash_password(body.password),role=body.role,is_active=True)
    session.add(user);await session.flush();session.add(AuditLog(actor_id=admin.id,action="user.created",resource_type="user",resource_id=str(user.id),details={"role":user.role}));await session.commit();await session.refresh(user);return user


@router.get("/users",response_model=list[UserRead])
async def list_users(
    response:Response,
    q:str="",
    role:str|None=None,
    active:bool|None=None,
    offset:int=Query(default=0,ge=0),
    limit:int=Query(default=50,ge=1,le=200),
    _admin:User=Depends(require_admin),
    session:AsyncSession=Depends(get_db_session),
):
    filters=[]
    if q:filters.append(or_(User.email.ilike(f"%{q}%"),User.display_name.ilike(f"%{q}%")))
    if role:filters.append(User.role==role)
    if active is not None:filters.append(User.is_active==active)
    response.headers["X-Total-Count"]=str(int(await session.scalar(select(func.count()).select_from(User).where(*filters)) or 0))
    return list((await session.scalars(select(User).where(*filters).order_by(User.created_at.desc()).offset(offset).limit(limit))).all())


@router.patch("/users/{user_id}",response_model=UserRead)
async def update_user(
    user_id,
    body:UserUpdate,
    admin:User=Depends(require_admin),
    session:AsyncSession=Depends(get_db_session),
):
    target=await session.get(User,user_id)
    if target is None:raise HTTPException(404,"User not found")
    changes=body.model_dump(exclude_none=True)
    if target.id==admin.id and changes.get("is_active") is False:
        raise HTTPException(409,"不能停用当前登录管理员")
    previous={key:getattr(target,key) for key in changes}
    for key,value in changes.items():setattr(target,key,value)
    session.add(AuditLog(actor_id=admin.id,action="user.updated",resource_type="user",resource_id=str(target.id),details={"from":previous,"to":changes}))
    await session.commit();await session.refresh(target);return target


@router.get("/audit-logs", response_model=list[AuditRead])
async def list_audit_logs(
    response:Response,
    q:str="",
    action:str|None=None,
    resource_type:str|None=None,
    offset:int=Query(default=0,ge=0),
    limit:int=Query(default=50,ge=1,le=200),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditLog]:
    filters=[]
    if q:filters.append(or_(AuditLog.action.ilike(f"%{q}%"),AuditLog.resource_type.ilike(f"%{q}%"),AuditLog.resource_id.ilike(f"%{q}%")))
    if action:filters.append(AuditLog.action==action)
    if resource_type:filters.append(AuditLog.resource_type==resource_type)
    response.headers["X-Total-Count"]=str(int(await session.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0))
    return list((await session.scalars(select(AuditLog).where(*filters).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit))).all())
