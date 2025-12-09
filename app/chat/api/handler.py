import asyncio
import json
import re
import uuid
from datetime import datetime
from fastapi import HTTPException
from typing import AsyncGenerator, Optional
from app.chat.api.dto import ChatRequest, ChatResponse
from app.agents.agent import CompanionAgent
from app.agents.base_agent import LLMModel
from app.chat.service.session_service import ConversationManager
from app.user.service.user_service import UserService
from app.agents.zep_user_service import ZepUserService
from app.core.logger import get_logger
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, UserPromptPart, TextPart

# Lazy initialization for agent instance (only create when needed)
_agent_instance: Optional[CompanionAgent] = None

def get_agent_instance() -> CompanionAgent:
    """Get or create the agent instance lazily."""
    global _agent_instance
    if _agent_instance is None:
        # Use GROQ_LLAMA_70B (FREE, FAST, and RELIABLE)
        _agent_instance = CompanionAgent(llm_model=LLMModel.GROQ_LLAMA_70B)
    return _agent_instance

logger = get_logger("ChatHandler")


def _is_valid_uuid(conversation_id: str) -> bool:
    """Validate if conversation_id is a valid UUID format."""
    if not conversation_id or not isinstance(conversation_id, str):
        return False
    try:
        uuid.UUID(conversation_id)
        return True
    except (ValueError, TypeError):
        return False


def _extract_error_message(error: Exception) -> str:
    """Extract a user-friendly error message from an exception."""
    error_str = str(error)
    
    # Handle rate limit errors (429)
    if "429" in error_str or "quota" in error_str.lower() or "rate limit" in error_str.lower():
        if "retry" in error_str.lower():
            # Try to extract retry delay
            retry_match = re.search(r'retry in ([\d.]+)s', error_str, re.IGNORECASE)
            if retry_match:
                return f"Rate limit exceeded. Please retry in {retry_match.group(1)} seconds."
        return "Rate limit exceeded. Please try again in a moment."
    
    # Handle authentication errors
    if "api_key" in error_str.lower() or "authentication" in error_str.lower() or "401" in error_str:
        return "Authentication error. Please check your API key configuration."
    
    # Handle model not found errors
    if "model" in error_str.lower() and ("not found" in error_str.lower() or "404" in error_str):
        return "Model not available. Please try a different model."
    
    # For other errors, return a simplified message
    # Limit the length to avoid overly verbose error messages
    if len(error_str) > 200:
        # Try to extract the main error message
        if "message" in error_str.lower():
            msg_match = re.search(r'message["\']?\s*:\s*["\']([^"\']+)', error_str, re.IGNORECASE)
            if msg_match:
                return msg_match.group(1)[:200]
        return error_str[:200] + "..."
    
    return error_str


def _convert_messages_to_model_messages(messages: list) -> list[ModelMessage]:
    """Convert messages to pydantic_ai ModelMessage format."""
    model_messages = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role")
            content = msg.get("content", "")
        else:
            role = msg.role
            content = msg.content
        
        if role == "user":
            model_messages.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif role == "assistant":
            model_messages.append(ModelResponse(parts=[TextPart(content=content)]))
        elif role == "system":
            model_messages.append(ModelRequest(parts=[UserPromptPart(content=content)]))
    return model_messages


def _get_conversation_messages(messages: list, skip_user_count: int = 0, count: int = 6) -> list[dict]:
    """
    Extract both user and assistant messages for title generation.
    The LLM will decide what's meaningful based on the prompt instructions.
    
    Args:
        messages: List of all messages (user + assistant)
        skip_user_count: Number of user messages to skip (not total messages)
        count: Maximum number of messages to return (includes both user and assistant)
    
    Returns:
        List of message dicts with 'role' and 'content' keys
    """
    conversation_messages = []
    user_count = 0
    
    for msg in messages:
        if len(conversation_messages) >= count:
            break
        
        if isinstance(msg, dict):
            role = msg.get("role")
            content = msg.get("content", "")
        else:
            role = msg.role
            content = msg.content
        
        if content and content.strip():
            # For user messages, apply skip logic
            if role == "user":
                if user_count < skip_user_count:
                    user_count += 1
                    continue
                user_count += 1
            
            # Include both user and assistant messages
            if role in ("user", "assistant"):
                conversation_messages.append({
                    "role": role,
                    "content": content
                })
    
    return conversation_messages


async def _try_generate_title(
    session_service: ConversationManager,
    conversation_id: str,
    messages: list,
    attempt: int = 1,
    max_attempts: int = 3
) -> Optional[str]:
    """
    Simplified title generation - just uses first user message as title.
    Note: TitleAgent has been removed. Consider implementing a simple LLM-based 
    title generator if needed in the future.
    """
    # Early check: if title already exists (not null and not "New Chat"), don't generate
    has_title = await session_service.has_title_generated(conversation_id)
    if has_title:
        conv_check = await session_service.get_conversation(conversation_id)
        existing_title = conv_check.get("title") if conv_check else None
        logger.info(f"[TitleGeneration] Conversation {conversation_id} already has title '{existing_title}'. Skipping generation.")
        return existing_title
    
    # Simple title generation: use first meaningful user message
    try:
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role")
                content = msg.get("content", "")
            else:
                role = getattr(msg, "role", None)
                content = getattr(msg, "content", "")
            
            if role == "user" and content and len(content.strip()) > 0:
                # Use first 50 characters of first user message as title
                title = content.strip()[:50]
                if len(content.strip()) > 50:
                    title += "..."
                
                # Double-check title wasn't set by another concurrent request
                has_title = await session_service.has_title_generated(conversation_id)
                if has_title:
                    conv_check = await session_service.get_conversation(conversation_id)
                    return conv_check.get("title") if conv_check else title
                
                await session_service.rename_conversation(conversation_id, title)
                logger.info(f"[TitleGeneration] Generated simple title: '{title}'")
                return title
        
        return None
    except Exception as e:
        logger.warning(f"[TitleGeneration] Title generation failed: {e}", exc_info=True)
        return None


async def handle_chat(
    body: ChatRequest,
    session_service: Optional[ConversationManager] = None,
    user_service: Optional[UserService] = None,
    zep_user_service: Optional[ZepUserService] = None
) -> ChatResponse:
    """Handles a non-streaming chat request."""
    try:
        # Build a prompt from messages (use last user message by default)
        prompt = next((m.content for m in reversed(body.messages) if m.role == "user"), body.messages[-1].content if body.messages else "")

        session_id = None
        message_history = None
        current_message_count = 0  # Initialize for cases without session_service

        # Parallelize session operations and user lookup for better latency
        postgres_user_id = body.user_id
        user_aggregate = None
        
        # Start both session operations and user lookup in parallel
        async def get_session_info():
            if not session_service:
                return None, None, 0, []
            
            if body.conversation_id and _is_valid_uuid(body.conversation_id):
                # User provided a valid conversation_id - use it if it exists and belongs to user
                conv = await session_service.get_conversation(body.conversation_id)
                if conv and conv.get("user_id") == body.user_id:
                    session_id = body.conversation_id
                else:
                    # Conversation doesn't exist or doesn't belong to user, create new one
                    session_id = await session_service.create_conversation(body.user_id)
            else:
                # Invalid or missing conversation_id - auto-generate a new one
                # Handle common placeholder values like "string", "null", etc.
                if body.conversation_id and not _is_valid_uuid(body.conversation_id):
                    if body.conversation_id.lower() not in ["string", "null", "undefined", ""]:
                        logger.debug(f"Invalid conversation_id format received: {body.conversation_id}, auto-generating new conversation")
                session_id = await session_service.create_conversation(body.user_id)

            # Load message history and get message count in parallel
            conv_messages_task = session_service.get_recent_messages(session_id, limit=100)
            conv_task = session_service.get_conversation(session_id)
            
            conv_messages, conv = await asyncio.gather(conv_messages_task, conv_task)
            message_history = _convert_messages_to_model_messages(conv_messages)
            current_message_count = conv.get("message_count", 0) if conv else 0

            # Save user's message (this increments message_count)
            await session_service.add_message(session_id, role="user", content=prompt)
            
            return session_id, message_history, current_message_count, conv
        
        async def get_user_info():
            if not (zep_user_service and user_service and body.user_id):
                return body.user_id, None
            
            try:
                user_agg = await user_service.get_user_by_id(body.user_id)
                if user_agg and user_agg.user:
                    pg_user_id = user_agg.user.id
                    # Ensure user exists in Zep with the SAME user_id as Postgres
                    await zep_user_service.ensure_user_exists(
                        user_id=pg_user_id,  # Same as Postgres user.id
                        email=user_agg.user.email,
                        name=user_agg.user.name,
                        metadata={"auth_provider": user_agg.user.auth_provider}
                    )
                    return pg_user_id, user_agg
            except Exception as e:
                logger.warning(f"Failed to ensure user exists in Zep before chat: {e}")
            return body.user_id, None
        
        # Run session and user operations in parallel
        if session_service:
            session_result, user_result = await asyncio.gather(
                get_session_info(),
                get_user_info()
            )
            session_id, message_history, current_message_count, conv = session_result
            postgres_user_id, user_aggregate = user_result
        else:
            # Fallback: use messages from request if no session_service
            _, user_result = await asyncio.gather(
                asyncio.sleep(0),  # Dummy task
                get_user_info()
            )
            session_id = None
            message_history = _convert_messages_to_model_messages(body.messages[:-1] if len(body.messages) > 1 else [])
            current_message_count = 0
            postgres_user_id, user_aggregate = user_result
        
        # Run the agent
        agent = get_agent_instance()
        
        # Pass zep_service to agent - it will create CompanionAgentDeps internally
        # The agent needs zep_service to fetch user memory context
        # Use postgres_user_id to ensure consistency with Zep
        if not zep_user_service:
            logger.warning("Zep user service not available - agent will run without memory context")
        
        # Fetch persistent user memory from Zep and prepend to message_history
        # SKIP Zep memory for the first message in a new conversation to avoid referencing past topics
        # Only load memory after the first exchange (message_count >= 1 after user message is saved)
        enhanced_message_history = list(message_history) if message_history else []
        if zep_user_service and postgres_user_id:
            # Use the message_count from BEFORE we saved the user message
            # This correctly identifies new conversations (count=0) vs continuing ones (count>0)
            message_count = current_message_count if session_service and session_id else 0
            
            # Skip Zep memory for the first message in a new conversation
            # This ensures fresh start without past context bleeding in
            if message_count > 0:
                # Only load memory for continuing conversations (after first exchange)
                user_context = await zep_user_service.get_user_context(postgres_user_id, message_count=message_count)
                if user_context:
                    # Prepend user memory as a system message to message_history
                    memory_content = f"# USER MEMORY (Persistent Preferences & Facts)\n{user_context}\n\nUse this memory to remember user preferences, facts, and context across conversations."
                    
                    # DEBUG: Log the full memory content being sent to LLM

                    
                    memory_system_message = ModelRequest(parts=[UserPromptPart(content=memory_content)])
                    enhanced_message_history = [memory_system_message] + enhanced_message_history
                else:
                    logger.info(f"[ChatHandler] No Zep memory context available for user {postgres_user_id} (message_count={message_count})")
            else:
                logger.info(f"[ChatHandler] Skipping Zep memory for new conversation (message_count={current_message_count if session_service and session_id else 0})")
        
        result = await agent.run(
            user_id=postgres_user_id or "",  # Same user_id used in Zep
            prompt=prompt,
            zep_service=zep_user_service,  # Required for memory context
            message_history=enhanced_message_history if enhanced_message_history else None
        )

        # Extract text from result
        text = result.data if hasattr(result, 'data') else str(result)

        # Save assistant message and store in Zep in parallel (non-blocking)
        user_timestamp = None
        assistant_timestamp = None
        
        async def save_assistant_message():
            if session_service and session_id:
                await session_service.add_message(session_id, role="assistant", content=text)
        
        async def store_in_zep():
            # Store messages in Zep (both user and assistant in one turn) - fire and forget
            if zep_user_service and postgres_user_id:
                try:
                    # Use cached user_aggregate if available, otherwise fetch
                    if not user_aggregate:
                        if user_service:
                            user_agg = await user_service.get_user_by_id(postgres_user_id)
                            user_name = user_agg.user.name if user_agg and user_agg.user and user_agg.user.name else ""
                        else:
                            user_name = ""
                    else:
                        user_name = user_aggregate.user.name if user_aggregate.user and user_aggregate.user.name else ""
                    
                    # Add chat turn to Zep (user + assistant together)
                    # Use postgres_user_id to ensure it matches the user_id in Zep
                    # Note: user_name can be empty - ZepUserService will handle fallback to "User"
                    await zep_user_service.add_chat_turn_to_zep(
                        user_id=postgres_user_id,  # Same as Postgres user.id, same as Zep user_id
                        user_name=user_name,
                        user_message=prompt,
                        assistant_message=text,
                        user_created_at=user_timestamp,
                        assistant_created_at=assistant_timestamp
                    )
                except Exception as e:
                    logger.warning(f"Failed to store messages in Zep: {e}")
                    # Continue even if Zep fails
        
        # Run both operations in parallel, but don't wait for Zep (fire-and-forget for better latency)
        if session_service and session_id:
            await save_assistant_message()
            
            # Check if conversation needs a title and generate it asynchronously
            async def generate_title_if_needed():
                try:
                    # Add a delay to avoid hitting rate limits right after companion agent call
                    # This gives the rate limit window time to reset
                    await asyncio.sleep(3)  # Wait 3 seconds before starting title generation
                    
                    # Check if title has been generated (not null and not "New Chat")
                    has_title = await session_service.has_title_generated(session_id)
                    if not has_title:
                        # Get all messages for title generation
                        all_messages = await session_service.get_recent_messages(session_id, limit=100)
                        messages_preview = [f"{m.get('role', 'unknown')}: {m.get('content', '')[:50]}" for m in all_messages[:10]]
                        logger.info(f"[TitleGeneration] Starting title generation for conversation {session_id}. "
                                   f"Total messages retrieved: {len(all_messages)}. "
                                   f"Messages: {messages_preview}")
                        if all_messages:
                            await _try_generate_title(session_service, session_id, all_messages)
                        else:
                            logger.info(f"[TitleGeneration] No messages found for conversation {session_id}")
                    else:
                        logger.info(f"[TitleGeneration] Conversation {session_id} already has a generated title. Skipping generation.")
                except Exception as e:
                    logger.warning(f"[TitleGeneration] Title generation task failed for conversation {session_id}: {e}", exc_info=True)
            
            # Generate title asynchronously (fire-and-forget)
            asyncio.create_task(generate_title_if_needed())
        
        # Store in Zep asynchronously without blocking response
        if zep_user_service and postgres_user_id:
            # Create task but don't await - fire and forget for better latency
            asyncio.create_task(store_in_zep())

        return ChatResponse(text=text, provider="agent")

    except Exception as e:
        logger.error(f"handle_chat error | error={e}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")



async def handle_chat_stream(
    body: ChatRequest,
    session_service: Optional[ConversationManager] = None,
    user_service: Optional[UserService] = None,
    zep_user_service: Optional[ZepUserService] = None
) -> AsyncGenerator[str, None]:
    """Handles a streaming chat request with SSE events for ultra-low latency."""

    session_id = None
    conversation_id = None
    full_response_text = ""
    current_message_count = 0  # Initialize for cases without session_service

    try:
        # Extract latest user prompt
        prompt = next(
            (m.content for m in reversed(body.messages) if m.role == "user"),
            body.messages[-1].content if body.messages else ""
        )

        # Parallelize session operations and user lookup for better latency
        postgres_user_id = body.user_id
        user_aggregate = None
        user_name = ""
        
        # Start both session operations and user lookup in parallel
        async def get_session_info():
            if not session_service:
                return None, None, 0, []
            
            if body.conversation_id and _is_valid_uuid(body.conversation_id):
                # User provided a valid conversation_id - use it if it exists and belongs to user
                conv = await session_service.get_conversation(body.conversation_id)
                if conv and conv.get("user_id") == body.user_id:
                    session_id = body.conversation_id
                    conversation_id = str(session_id)
                else:
                    # Conversation doesn't exist or doesn't belong to user, create new one
                    session_id = await session_service.create_conversation(body.user_id)
                    conversation_id = str(session_id)
            else:
                # Invalid or missing conversation_id - auto-generate a new one
                # Handle common placeholder values like "string", "null", etc.
                if body.conversation_id and not _is_valid_uuid(body.conversation_id):
                    if body.conversation_id.lower() not in ["string", "null", "undefined", ""]:
                        logger.debug(f"Invalid conversation_id format received: {body.conversation_id}, auto-generating new conversation")
                session_id = await session_service.create_conversation(body.user_id)
                conversation_id = str(session_id)

            # Load message history and get message count in parallel
            conv_messages_task = session_service.get_recent_messages(session_id, limit=100)
            conv_task = session_service.get_conversation(session_id)
            
            conv_messages, conv = await asyncio.gather(conv_messages_task, conv_task)
            message_history = _convert_messages_to_model_messages(conv_messages)
            current_message_count = conv.get("message_count", 0) if conv else 0

            # Save user's message (this increments message_count)
            await session_service.add_message(session_id, role="user", content=prompt)
            
            return session_id, conversation_id, message_history, current_message_count
        
        async def get_user_info():
            if not (zep_user_service and user_service and body.user_id):
                return body.user_id, None, ""
            
            try:
                user_agg = await user_service.get_user_by_id(body.user_id)
                if user_agg and user_agg.user:
                    pg_user_id = user_agg.user.id
                    user_nm = user_agg.user.name if user_agg.user.name else ""
                    # Ensure user exists in Zep with the SAME user_id as Postgres
                    await zep_user_service.ensure_user_exists(
                        user_id=pg_user_id,  # Same as Postgres user.id
                        email=user_agg.user.email,
                        name=user_agg.user.name,
                        metadata={"auth_provider": user_agg.user.auth_provider}
                    )
                    return pg_user_id, user_agg, user_nm
            except Exception as e:
                logger.warning(f"Failed to ensure user exists in Zep before chat: {e}")
            return body.user_id, None, ""
        
        # Run session and user operations in parallel
        if session_service:
            session_result, user_result = await asyncio.gather(
                get_session_info(),
                get_user_info()
            )
            session_id, conversation_id, message_history, current_message_count = session_result
            postgres_user_id, user_aggregate, user_name = user_result
        else:
            # Fallback: use messages from request if no session_service
            _, user_result = await asyncio.gather(
                asyncio.sleep(0),  # Dummy task
                get_user_info()
            )
            session_id = None
            conversation_id = None
            message_history = _convert_messages_to_model_messages(body.messages[:-1] if len(body.messages) > 1 else [])
            current_message_count = 0
            postgres_user_id, user_aggregate, user_name = user_result

        # Send start event
        start_payload = {"conversation_id": conversation_id} if conversation_id else {}
        yield f"event: start\ndata: {json.dumps(start_payload)}\n\n"

        # Run agent stream
        agent = get_agent_instance()
        
        # Pass zep_service to agent - it will create CompanionAgentDeps internally
        # The agent needs zep_service to fetch user memory context
        # Use postgres_user_id to ensure consistency with Zep
        if not zep_user_service:
            logger.warning("Zep user service not available - agent will run without memory context")
        
        # Fetch persistent user memory from Zep and prepend to message_history
        # SKIP Zep memory for the first message in a new conversation to avoid referencing past topics
        # Only load memory after the first exchange (message_count >= 1 after user message is saved)
        enhanced_message_history = list(message_history) if message_history else []
        if zep_user_service and postgres_user_id:
            # Use the message_count from BEFORE we saved the user message
            # This correctly identifies new conversations (count=0) vs continuing ones (count>0)
            message_count = current_message_count if session_service and session_id else 0
            
            # Skip Zep memory for the first message in a new conversation
            # This ensures fresh start without past context bleeding in
            if message_count > 0:
                # Only load memory for continuing conversations (after first exchange)
                user_context = await zep_user_service.get_user_context(postgres_user_id, message_count=message_count)
                if user_context:
                    # Prepend user memory as a system message to message_history
                    memory_content = f"# USER MEMORY (Persistent Preferences & Facts)\n{user_context}\n\nUse this memory to remember user preferences, facts, and context across conversations."
                    
                    # DEBUG: Log the full memory content being sent to LLM
                    
                    memory_system_message = ModelRequest(parts=[UserPromptPart(content=memory_content)])
                    enhanced_message_history = [memory_system_message] + enhanced_message_history
                else:
                    logger.info(f"[ChatHandler] No Zep memory context available for user {postgres_user_id} (message_count={message_count})")
            else:
                logger.info(f"[ChatHandler] Skipping Zep memory for new conversation (message_count={current_message_count if session_service and session_id else 0})")

        async with agent.run_stream(
            user_id=postgres_user_id or "",  # Same user_id used in Zep
            prompt=prompt,
            zep_service=zep_user_service,  # Required for memory context
            message_history=enhanced_message_history if enhanced_message_history else None
        ) as agent_result:

            # Ultra-low latency streaming: send every delta immediately
            async for chunk in agent_result.stream_text(delta=True):
                if chunk.strip():
                    full_response_text += chunk
                    event_data = json.dumps({"type": "text_delta", "text": chunk}, ensure_ascii=False)
                    yield f"event: content_block_delta\ndata: {event_data}\n\n"

        # Complete & done events
        complete_payload = {"conversation_id": conversation_id} if conversation_id else {}
        yield f"event: complete\ndata: {json.dumps(complete_payload)}\n\n"
        yield f"event: done\ndata: {json.dumps(complete_payload)}\n\n"

        # Save assistant message and get timestamps for Zep
        from datetime import datetime
        user_timestamp = datetime.utcnow()
        assistant_timestamp = datetime.utcnow()
        
        async def store_in_zep():
            # Store messages in Zep (both user and assistant in one turn) - fire and forget
            if zep_user_service and postgres_user_id and full_response_text:
                try:
                    # Use cached user_name if available, otherwise fetch
                    if not user_name and user_service:
                        user_agg = await user_service.get_user_by_id(postgres_user_id)
                        user_nm = user_agg.user.name if user_agg and user_agg.user and user_agg.user.name else ""
                    else:
                        user_nm = user_name
                    
                    # Add chat turn to Zep (user + assistant together)
                    await zep_user_service.add_chat_turn_to_zep(
                        user_id=postgres_user_id,
                        user_name=user_nm,
                        user_message=prompt,
                        assistant_message=full_response_text,
                        user_created_at=user_timestamp,
                        assistant_created_at=assistant_timestamp
                    )
                except Exception as e:
                    logger.warning(f"Failed to store messages in Zep: {e}")
                    # Continue even if Zep fails
        
        # Save assistant message (needed for summary event)
        if session_service and session_id and full_response_text:
            await session_service.add_message(session_id, role="assistant", content=full_response_text)
            conv_meta = await session_service.get_conversation(str(session_id))
            if conv_meta and isinstance(conv_meta, dict):
                msg_count = conv_meta.get("message_count")
                if msg_count is not None:
                    yield f"event: summary\ndata: {json.dumps({'message_count': msg_count})}\n\n"
            
            # Check if conversation needs a title and generate it asynchronously
            async def generate_title_if_needed():
                try:
                    # Delay to avoid rate limits right after companion agent call
                    await asyncio.sleep(3)
                    
                    # Check if title has been generated (not null and not "New Chat")
                    has_title = await session_service.has_title_generated(session_id)
                    if not has_title:
                        all_messages = await session_service.get_recent_messages(session_id, limit=100)
                        if all_messages:
                            await _try_generate_title(session_service, session_id, all_messages)
                        else:
                            logger.info(f"[TitleGeneration] No messages found for conversation {session_id}")
                    else:
                        logger.info(f"[TitleGeneration] Conversation {session_id} already has a generated title. Skipping title agent call.")
                except Exception as e:
                    logger.warning(f"[TitleGeneration] Title generation task failed: {e}", exc_info=True)
            
            # Generate title asynchronously (fire-and-forget)
            asyncio.create_task(generate_title_if_needed())
        
        # Store in Zep asynchronously without blocking response (fire-and-forget for better latency)
        if zep_user_service and postgres_user_id and full_response_text:
            # Create task but don't await - fire and forget for better latency
            asyncio.create_task(store_in_zep())

    except Exception as e:
        logger.error(f"Streaming error: {e}")
        if session_service and session_id and full_response_text:
            await session_service.add_message(session_id, role="assistant", content=full_response_text)
            
            # Still try to store in Zep even on error (fire-and-forget)
            # Use postgres_user_id if available (from earlier in the function)
            if zep_user_service and postgres_user_id and full_response_text:
                async def store_in_zep_on_error():
                    try:
                        # Get user name if not already cached
                        user_nm = user_name if user_name else ""
                        if not user_nm and user_service:
                            try:
                                user_agg = await user_service.get_user_by_id(postgres_user_id)
                                user_nm = user_agg.user.name if user_agg and user_agg.user and user_agg.user.name else ""
                            except Exception:
                                pass
                        
                        # Add chat turn to Zep (user + assistant together)
                        await zep_user_service.add_chat_turn_to_zep(
                            user_id=postgres_user_id,
                            user_name=user_nm,
                            user_message=prompt,
                            assistant_message=full_response_text
                        )
                    except Exception as zep_error:
                        logger.warning(f"Failed to store messages in Zep after error: {zep_error}")
                
                # Fire and forget - don't block error response
                asyncio.create_task(store_in_zep_on_error())

        error_msg = _extract_error_message(e)
        yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"

