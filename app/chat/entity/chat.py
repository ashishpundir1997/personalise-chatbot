# app/chat/entity/chat.py
"""
DTO models for Conversation and Message.
These models represent the structure of chat session data.
"""

from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(BaseModel):
    """Message DTO representing a single message in a conversation."""
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    created_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class Conversation(BaseModel):
    """Conversation DTO representing a chat session."""
    conversation_id: str
    user_id: str
    created_at: Optional[str] = None
    last_activity: Optional[str] = None
    message_count: int = 0
    messages: Optional[List[Message]] = Field(default_factory=list)

