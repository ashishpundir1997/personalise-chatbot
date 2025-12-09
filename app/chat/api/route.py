from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Optional
from app.chat.api.dto import ChatRequest, ChatResponse, ConversationResponse, DeleteResponse, RenameConversationDTO
from app.chat.api.handler import handle_chat, handle_chat_stream
from app.chat.service.session_service import ConversationManager
from app.user.service.user_service import UserService
from app.agents.zep_user_service import ZepUserService
from app.core.logger import get_logger
from app.auth.api.dependencies import get_current_user
from app.auth.api.dto import BaseResponse

chat_router = APIRouter(prefix="/chat", tags=["Chat"])
logger = get_logger("ChatRouter")


def get_session_service(request: Request) -> Optional[ConversationManager]:
    """Dependency to get session service from app.state."""
    return getattr(request.app.state, "session_service", None)


def get_user_service(request: Request) -> Optional[UserService]:
    """Dependency to get user service from app.state."""
    return getattr(request.app.state, "user_service", None)


def get_zep_user_service(request: Request) -> Optional[ZepUserService]:
    """Dependency to get Zep user service from app.state."""
    return getattr(request.app.state, "zep_user_service", None)




@chat_router.post("", response_class=JSONResponse)
async def chat_api(
    body: ChatRequest,
    current_user: dict = Depends(get_current_user),
    session_service: Optional[ConversationManager] = Depends(get_session_service),
    user_service: Optional[UserService] = Depends(get_user_service),
    zep_user_service: Optional[ZepUserService] = Depends(get_zep_user_service)
):
    """Non-streaming chat endpoint."""
    # Add authenticated user_id to request
    body.user_id = current_user["user_id"]
    response = await handle_chat(body, session_service, user_service, zep_user_service)
    return response


@chat_router.post("/stream")
async def chat_stream_api(
    body: ChatRequest,
    current_user: dict = Depends(get_current_user),
    session_service: Optional[ConversationManager] = Depends(get_session_service),
    user_service: Optional[UserService] = Depends(get_user_service),
    zep_user_service: Optional[ZepUserService] = Depends(get_zep_user_service)
):
    """
    Streaming chat endpoint (Server-Sent Events).
    The router already returns SSE-formatted chunks, so we just forward them.
    """
    # Add authenticated user_id to request
    body.user_id = current_user["user_id"]
    async def event_generator():
        async for event in handle_chat_stream(body, session_service, user_service, zep_user_service):
            # Forward the event as-is — no extra wrapping!
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # for Nginx
        },
    )


@chat_router.get("/conversation/{conversation_id}", response_model=BaseResponse)
async def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    session_service: Optional[ConversationManager] = Depends(get_session_service),
    include_messages: bool = Query(default=True, description="Include messages in response"),
    limit: int = Query(default=25, ge=1, le=50, description="Number of messages to return per page. Frontend should always use 25 for consistent UX. Backend allows 1-50 for flexibility."),
    cursor: Optional[str] = Query(default=None, description="Cursor for pagination (timestamp of oldest message from previous request)")
):
    """
    Get conversation by conversation_id with cursor-based pagination.
    Returns conversation metadata and optionally messages.
    
    Uses cursor-based pagination: load 25 messages per request for infinite scroll.
    
    Note: Frontend should always use limit=25 for consistent UX.
    Backend allows 1-50 for API flexibility, but frontend must use 25.
    
    its follwoing order from below latest to top older
    """
    if not session_service:
        raise HTTPException(status_code=503, detail="Session service not available")
    
    try:
        # Get conversation metadata
        conv = await session_service.get_conversation(conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
        
        # Verify user owns this conversation
        if conv["user_id"] != current_user["user_id"]:
            raise HTTPException(status_code=403, detail="Access denied: You don't own this conversation")
        
        # Handle backward compatibility: use last_activity if available, otherwise updated_at
        last_activity = conv.get("last_activity") or conv.get("updated_at")
        if not last_activity:
            raise HTTPException(status_code=500, detail="Conversation data is missing last_activity field")
        
        # Use "New Chat" as default if title is null
        title = conv.get("title") or "New Chat"
        response_data = ConversationResponse(
            conversation_id=conv["conversation_id"],
            user_id=conv["user_id"],
            created_at=conv["created_at"],
            last_activity=last_activity,
            message_count=conv["message_count"],
            title=title,  # Use 'title' instead of 'name', default to "New Chat"
        )
        
        # Include messages if requested
        if include_messages:
            messages, has_more, next_cursor = await session_service.get_messages_paginated(
                conversation_id, 
                limit=limit, 
                cursor=cursor
            )
            response_data.messages = messages
            response_data.returned_messages = len(messages)
            response_data.has_more_messages = has_more
            response_data.next_cursor = next_cursor
        else:
            response_data.returned_messages = 0
            response_data.has_more_messages = conv["message_count"] > 0
            response_data.next_cursor = None
        
        logger.info(f"Retrieved conversation_id={conversation_id} (include_messages={include_messages}, limit={limit}, cursor={cursor})")
        
        # Return standardized response format
        return BaseResponse(
            status=True,
            message="Conversation fetched successfully",
            data=response_data.model_dump()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve conversation: {str(e)}")


@chat_router.patch("/conversation/{conversation_id}/rename", response_model=BaseResponse)
async def rename_conversation(
    conversation_id: str,
    rename_data: RenameConversationDTO,
    current_user: dict = Depends(get_current_user),
    session_service: Optional[ConversationManager] = Depends(get_session_service)
):

    if not session_service:
        raise HTTPException(status_code=503, detail="Session service not available")
    
    try:
        # Validate conversation exists
        conv = await session_service.get_conversation(conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
        
        # Verify user owns this conversation
        if conv["user_id"] != current_user["user_id"]:
            raise HTTPException(status_code=403, detail="Access denied: You don't own this conversation")
        
        # Rename conversation
        await session_service.rename_conversation(conversation_id, rename_data.name)
        
        logger.info(f"Renamed conversation_id={conversation_id} to '{rename_data.name}'")
        
        # Get updated conversation to return the title
        updated_conv = await session_service.get_conversation(conversation_id)
        
        # Return standardized response format
        return BaseResponse(
            status=True,
            message="Conversation renamed successfully",
            data={
                "conversation_id": conversation_id,
                "title": updated_conv.get("title") if updated_conv else rename_data.name
            }
        )
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error renaming conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to rename conversation: {str(e)}")


@chat_router.delete("/conversation/{conversation_id}", response_model=BaseResponse)
async def delete_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    session_service: Optional[ConversationManager] = Depends(get_session_service)
):
    """
    Delete conversation by conversation_id.
    Deletes conversation and all related messages from both Redis and Postgres.
    """
    if not session_service:
        raise HTTPException(status_code=503, detail="Session service not available")
    
    try:
        # Validate conversation exists before deleting
        conv = await session_service.get_conversation(conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
        
        # Verify user owns this conversation
        if conv["user_id"] != current_user["user_id"]:
            raise HTTPException(status_code=403, detail="Access denied: You don't own this conversation")
        
        # Delete conversation
        await session_service.delete_conversation(conversation_id)
        
        logger.info(f"Deleted conversation_id={conversation_id}")
        
        # Return standardized response format
        return BaseResponse(
            status=True,
            message=f"Conversation deleted successfully",
            data={
                "conversation_id": conversation_id
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete conversation: {str(e)}")



@chat_router.get("/conversations", response_model=BaseResponse)
async def list_conversations(
    current_user: dict = Depends(get_current_user),
    session_service: Optional[ConversationManager] = Depends(get_session_service),
    limit: int = Query(default=20, ge=1, le=50, description="Number of items to return"),
    offset: int = Query(default=0, ge=0, description="Start offset for pagination"),
):
    """Paginated list of conversations for the authenticated user (default limit 20)."""
    if not session_service:
        raise HTTPException(status_code=503, detail="Session service not available")

    try:
        items = await session_service.list_conversations(current_user["user_id"], limit=limit, offset=offset)
        # Ensure each item includes conversation_id (already named so)
        next_offset = offset + len(items)
        
        # Return standardized response format
        return BaseResponse(
            status=True,
            message="Conversations fetched successfully",
            data={
                "conversations": items,
                "limit": limit,
                "offset": offset,
                "next_offset": next_offset
            }
        )
    except Exception as e:
        logger.error(f"Error listing conversations for user_id={current_user['user_id']}: {e}")
        raise HTTPException(status_code=500, detail="Failed to list conversations")