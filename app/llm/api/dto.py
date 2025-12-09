# app/llm/api/dto.py
from pydantic import BaseModel, Field
from typing import List, Optional, Literal


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class GenerateParams(BaseModel):
    model: Optional[str] = Field(default="gpt-4o-mini")
    temperature: Optional[float] = Field(default=0.7)
    max_tokens: Optional[int] = Field(default=512)
    stream: Optional[bool] = Field(default=False)


class GenerateRequest(BaseModel):
    messages: List[Message]
    params: Optional[GenerateParams] = None


class GenerateResponse(BaseModel):
    response: str
    model_used: str
    latency_ms: Optional[int] = None


class ProviderChunk(BaseModel):
    provider: str
    content: Optional[str] = None
    delta: Optional[str] = None
    finish_reason: Optional[str] = None
    timestamp: Optional[str] = None


class ProviderInfo(BaseModel):
    name: str
    latency_ms: Optional[int]
    status: str


class ProviderListResponse(BaseModel):
    providers: List[ProviderInfo]
