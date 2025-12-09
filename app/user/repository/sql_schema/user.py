from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from pkg.db_util.sql_alchemy.declarative_base import Base
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class UserModel(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=True)
    auth_provider = Column(String, default="email")  # 'email' or 'google'
    auth_provider_detail = Column(JSONB, nullable=True)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    is_email_verified = Column(Boolean, default=False)
    is_profile_created = Column(Boolean, default=False)
    profile_colour = Column(String, nullable=True, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
