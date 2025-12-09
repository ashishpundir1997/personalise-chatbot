from datetime import datetime
from uuid import uuid4
from typing import Optional
from pydantic import BaseModel, Field


class Entity(BaseModel):
    id: str = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)



class User(Entity):
    email: str
    password_hash: Optional[str] = None 
    name: str = ""
    is_active: bool = True
    auth_provider: str = "email"
    phone: str = ""
    is_profile_created: bool = False
    is_email_verified: bool = False
    image_url: str = ""
    profile_colour: str = ""


