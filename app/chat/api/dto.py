from pydantic import BaseModel, Field
from typing import List, Literal, Optional


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]
    stream: bool = True
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    text: str
    provider: str


class ConversationResponse(BaseModel):
    conversation_id: str
    user_id: str
    created_at: str
    last_activity: str
    message_count: int
    title: str | None = None  # Changed from 'name' to 'title'
    
    messages: Optional[List[dict]] = None
    # Pagination metadata for messages
    returned_messages: Optional[int] = None  # Number of messages actually returned
    has_more_messages: Optional[bool] = None  # Whether there are more messages available
    next_cursor: Optional[str] = None  # Cursor for loading older messages (timestamp of oldest message in batch)


class DeleteResponse(BaseModel):
    success: bool
    message: str
    conversation_id: str


class RenameConversationDTO(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="New name for the conversation")