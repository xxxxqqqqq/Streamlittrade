from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class ProjectCreate(BaseModel):
    name:str=Field(min_length=2,max_length=120);slug:str=Field(pattern=r"^[a-z0-9_-]+$")
class ProjectRead(BaseModel):
    model_config=ConfigDict(from_attributes=True);id:UUID;owner_id:UUID;name:str;slug:str;created_at:datetime;member_role:str|None=None
class MemberCreate(BaseModel):
    user_id:UUID;role:Literal["admin","researcher","viewer"]="researcher"
class MemberRead(BaseModel):
    model_config=ConfigDict(from_attributes=True);id:UUID;project_id:UUID;user_id:UUID;role:str;created_at:datetime
class MemberDetail(MemberRead):
    email:str
    display_name:str
class MemberUpdate(BaseModel):
    role:Literal["admin","researcher","viewer"]
