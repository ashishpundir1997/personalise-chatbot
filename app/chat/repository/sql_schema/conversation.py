from sqlalchemy import (
    Column, String, DateTime, Integer, Text, ForeignKey
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid
from datetime import timezone

from pkg.db_util.sql_alchemy.declarative_base import Base

# Conversation Table
class ConversationModel(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_activity = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    message_count = Column(Integer, nullable=False, default=0)
    # conversation display name (first 4 words of first user message)
    name = Column(String, nullable=True)
    # model = Column(String, nullable=True)




# Message Table

class MessageModel(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False, index=True)
    sender_role = Column(String, nullable=False)
    content = Column(Text, nullable=True)
    message_metadata = Column(JSONB, nullable=True)  # Renamed from 'metadata' (SQLAlchemy reserved name)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)