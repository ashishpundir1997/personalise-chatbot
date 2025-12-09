# app/chat/model/chat_models.py
from datetime import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Represents a single message in a chat session."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChatTurn(BaseModel):
    """Represents a full user-assistant interaction."""
    user_message: ChatMessage
    assistant_message: Optional[ChatMessage] = None
    provider_used: Optional[str] = None
    latency_ms: Optional[float] = None


class ChatSession(BaseModel):
    """Represents an ongoing chat session with history."""
    session_id: str
    messages: List[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    active_provider: Optional[str] = None
    total_tokens: Optional[int] = 0
