
import logging
import asyncio
import re
from datetime import datetime
from typing import Optional, List
from zep_cloud import Zep
from zep_cloud.types import Message as ZepMessage
from app.agents.zep_client import get_zep_client


class ZepUserService:
    """Service for managing users in Zep"""
    
    # Context template ID for companion agent
    CONTEXT_TEMPLATE_ID = "companion-agent-context"
    

    CONTEXT_TEMPLATE_CONTENT = """

# USER PROFILE & FACTS

%{user_summary}

# KEY USER ENTITIES & TRAITS

%{entities types=[person,personality_trait,skill,hobby,goal,fact,preference,location,occupation,relationship] limit=20}

# USER INTERESTS & TOPICS

%{entities types=[topic,interest,technology,project] limit=15}

# DO NOT INCLUDE EMOTIONAL STATES OR TEMPORAL CONTEXT

%{edges types=[emotion,feeling,mood] limit=0}

%{entities types=[emotion,feeling,mood] limit=0}

IMPORTANT: This memory contains PERSISTENT USER FACTS - who they are, what they do, their interests, skills, and preferences.
Use this to build a personality profile when the user asks "Who am I?" or "Tell me about myself."

"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._client: Optional[Zep] = None
        self._template_ensured = False
    
    @property
    def client(self) -> Zep:
        """Lazy initialization of Zep client"""
        if self._client is None:
            try:
                self._client = get_zep_client()
            except Exception as e:
                self.logger.error(f"Failed to initialize Zep client: {e}")
                raise
        return self._client
    
    def _parse_name(self, name: str) -> tuple[str, Optional[str]]:
        """
        Parse full name into first_name and last_name.
        Returns (first_name, last_name)
        """
        if not name or not name.strip():
            return ("", None)
        
        name_parts = name.strip().split(maxsplit=1)
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[1] if len(name_parts) > 1 else None
        
        return (first_name, last_name)
    
    async def create_or_update_user(
        self,
        user_id: str,
        email: str,
        name: str = "",
        metadata: Optional[dict] = None
    ) -> bool:
        try:
            first_name, last_name = self._parse_name(name)
            
            # Prepare user data
            user_data = {
                "user_id": user_id,
                "email": email,
                "first_name": first_name,
            }
            
            if last_name:
                user_data["last_name"] = last_name
            
            if metadata:
                user_data["metadata"] = metadata
            
            # Create or update user in Zep
            # Use run_in_executor to avoid blocking the event loop
            await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: self.client.user.add(**user_data)
            )
            
            self.logger.info(f"Successfully created/updated user in Zep: {user_id} ({email})")
            return True
            
        except Exception as e:
            error_str = str(e)
            # Check if user already exists - this is expected and not an error
            if "already exists" in error_str.lower() or ("400" in error_str and "user" in error_str.lower()):
                self.logger.info(f"User {user_id} already exists in Zep (idempotent operation succeeded)")
                return True
            # For actual errors, log as error
            self.logger.error(f"Failed to create/update user in Zep: {user_id}, error: {e}")
            # Don't raise exception - allow auth to continue even if Zep fails
            return False
    
    async def ensure_user_exists(
        self,
        user_id: str,
        email: str,
        name: str = "",
        metadata: Optional[dict] = None
    ) -> bool:
        return await self.create_or_update_user(user_id, email, name, metadata)
    
    async def create_thread_for_user(self, user_id: str) -> Optional[str]:
        try:
            # Use deterministic thread_id to ensure one persistent thread per user
            thread_id = f"{user_id}_thread"
            
            # Create thread (Zep's API is idempotent - won't error if thread already exists)
            # Note: This will fail with 404 if user doesn't exist in Zep
            # Use run_in_executor to avoid blocking the event loop
            await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: self.client.thread.create(
                    thread_id=thread_id,
                    user_id=user_id,
                )
            )
            self.logger.info(f"[Zep] Created/verified thread_id={thread_id} for user_id={user_id}")
            return thread_id
        except Exception as e:
            error_str = str(e)
            # Check if thread already exists - this is expected and not an error (idempotent operation)
            if "already exists" in error_str.lower() or ("400" in error_str and ("session" in error_str.lower() or "thread" in error_str.lower())):
                self.logger.info(f"[Zep] Thread {thread_id} already exists for user_id={user_id} (idempotent operation succeeded)")
                return thread_id
            # Check if it's a "user not found" error
            if "user not found" in error_str.lower() or "404" in error_str:
                self.logger.warning(f"User {user_id} not found in Zep. Thread creation requires user to exist first.")
                return None
            # For other actual errors, log as error
            self.logger.error(f"Failed to create thread for user {user_id} in Zep: {e}")
            return None
    
    def _get_thread_id(self, user_id: str) -> str:
        """Get the deterministic thread_id for a user."""
        return f"{user_id}_thread"
    
    async def ensure_context_template(self, max_retries: int = 2, initial_delay: float = 0.5, force_update: bool = False):
        """
        Ensure the context template exists with the correct content. Creates or updates it if needed.
        This template defines how Zep formats memory when retrieved.
        Used in get_user_context() to format memory before passing to LLM.
        
        Checks template existence and content. If template exists but content differs, updates it.
        Retries on 503 errors with exponential backoff.
        
        Args:
            max_retries: Maximum number of retry attempts for 503 errors (default: 2)
            initial_delay: Initial delay in seconds before first retry (default: 0.5)
            force_update: If True, delete and recreate template even if it exists (default: False)
        """
        if self._template_ensured and not force_update:
            return
        
        # Check if template exists and compare content
        template_needs_update = False
        if not force_update:
            try:
                existing_template = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: self.client.context.get_context_template(template_id=self.CONTEXT_TEMPLATE_ID)
                )
                # Template exists - check if content matches
                if hasattr(existing_template, 'template') and existing_template.template != self.CONTEXT_TEMPLATE_CONTENT:
                    template_needs_update = True
                    self.logger.info(f"[Zep] Template {self.CONTEXT_TEMPLATE_ID} exists but content differs, will update")
                elif hasattr(existing_template, 'template'):
                    # Template exists and content matches
                    self.logger.debug(f"[Zep] Context template {self.CONTEXT_TEMPLATE_ID} already exists with correct content")
                    self._template_ensured = True
                    return
            except Exception as e:
                error_str = str(e)
                # 404 means template doesn't exist - proceed to create
                if "404" in error_str or "not found" in error_str.lower():
                    self.logger.debug(f"[Zep] Template {self.CONTEXT_TEMPLATE_ID} not found, will create")
                else:
                    # Other errors during check - log but continue to creation attempt
                    self.logger.debug(f"[Zep] Error checking template existence: {type(e).__name__}, will attempt creation")
        
        # Delete existing template if we need to update it
        if force_update or template_needs_update:
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: self.client.context.delete_context_template(template_id=self.CONTEXT_TEMPLATE_ID)
                )
                self.logger.info(f"[Zep] Deleted existing template {self.CONTEXT_TEMPLATE_ID} for update")
            except Exception as e:
                error_str = str(e)
                # 404 is fine - template doesn't exist, we'll create it
                if "404" not in error_str and "not found" not in error_str.lower():
                    self.logger.warning(f"[Zep] Error deleting template for update: {e}, will attempt to create anyway")
        
        # Create the template with retry logic
        for attempt in range(max_retries + 1):
            try:
                # Create the template (idempotent - won't error if already exists)
                # Use run_in_executor to avoid blocking the event loop
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: self.client.context.create_context_template(
                        template_id=self.CONTEXT_TEMPLATE_ID,
                        template=self.CONTEXT_TEMPLATE_CONTENT
                    )
                )
                self.logger.info(f"[Zep] Created/updated context template: {self.CONTEXT_TEMPLATE_ID}")
                self.logger.debug(f"[Zep] Template structure: USER PREFERENCES, PREFERENCE ENTITIES, PERMANENT FACT ENTITIES, GOALS, TECHNICAL INTERESTS (excludes emotional memory and episodes)")
                self._template_ensured = True
                return
            except Exception as e:
                error_str = str(e)
                
                # Template might already exist - that's fine (idempotent operation)
                if "already exists" in error_str.lower() or ("400" in error_str and "template" in error_str.lower()):
                    self.logger.info(f"[Zep] Context template {self.CONTEXT_TEMPLATE_ID} already exists (idempotent operation succeeded)")
                    self._template_ensured = True
                    return
                
                # Handle 503 errors with retry logic
                is_503 = "503" in error_str or "temporarily unavailable" in error_str.lower()
                
                if is_503 and attempt < max_retries:
                    # Exponential backoff: delay = initial_delay * (2 ^ attempt)
                    delay = initial_delay * (2 ** attempt)
                    self.logger.warning(
                        f"[Zep] Zep service temporarily unavailable (503) during template creation. "
                        f"Retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries + 1})"
                    )
                    await asyncio.sleep(delay)
                    continue
                elif is_503:
                    # Final attempt failed with 503 - template may already exist, so this is not critical
                    self.logger.info(
                        f"[Zep] Template creation unavailable after {max_retries + 1} attempts (503). "
                        f"Template may already exist, will attempt to use existing template."
                    )
                    return
                else:
                    # For other errors, log at info level since template may already exist
                    self.logger.info(f"[Zep] Template creation had an issue (may already exist): {type(e).__name__}: {e}")
                    return
    
    async def add_messages_to_thread(
        self,
        user_id: str,
        user_name: str,
        messages: List[dict],
    ) -> bool:
        try:
            thread_id = self._get_thread_id(user_id)
            
            # Ensure thread exists
            await self.create_thread_for_user(user_id)
            
            # Convert messages to Zep Message format
            zep_messages = []
            now = datetime.utcnow()
            
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                msg_timestamp = msg.get("created_at")
                
                # Truncate content if exceeds Zep's limit (2500 characters)
                if len(content) > 2500:
                    self.logger.warning(f"Message content truncated from {len(content)} to 2500 characters for user {user_id}")
                    content = content[:2500]
                
                # Determine name based on role
                # Always provide a meaningful name for better entity extraction
                if role == "user":
                    # Use user_name if provided and not empty, otherwise fallback to "User"
                    name = user_name.strip() if user_name and user_name.strip() else "User"
                elif role == "assistant":
                    name = "Neo"  # Assistant name
                else:
                    name = role.capitalize()
                
                # Format timestamp in RFC3339 format
                if msg_timestamp:
                    if isinstance(msg_timestamp, datetime):
                        created_at_str = msg_timestamp.isoformat() + "Z"
                    else:
                        created_at_str = str(msg_timestamp)
                else:
                    created_at_str = now.isoformat() + "Z"
                
                zep_message = ZepMessage(
                    name=name,
                    role=role,
                    content=content,
                    created_at=created_at_str
                )
                zep_messages.append(zep_message)
            
            # Add messages to Zep thread (max 30 messages per call)
            # Use run_in_executor to avoid blocking the event loop for each network call
            # Process batches sequentially to avoid overwhelming the API
            if len(zep_messages) > 30:
                self.logger.warning(f"Too many messages ({len(zep_messages)}), splitting into batches of 30")
                # Split into batches of 30 and process sequentially
                for i in range(0, len(zep_messages), 30):
                    batch = zep_messages[i:i+30]
                    # Capture batch in lambda default argument to avoid closure issue
                    await asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda batch=batch: self.client.thread.add_messages(thread_id, messages=batch)
                    )
            else:
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: self.client.thread.add_messages(thread_id, messages=zep_messages)
                )
            
            self.logger.info(f"Added {len(zep_messages)} messages to Zep thread {thread_id} for user {user_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to add messages to Zep thread for user {user_id}: {e}")
            # Don't raise exception - allow chat to continue even if Zep fails
            return False
    
    async def add_chat_turn_to_zep(
        self,
        user_id: str,
        user_name: str,
        user_message: str,
        assistant_message: str,
        user_created_at: Optional[datetime] = None,
        assistant_created_at: Optional[datetime] = None
    ) -> bool:
        now = datetime.utcnow()
        user_timestamp = user_created_at or now
        
        # If assistant timestamp not provided, use user timestamp + 1 second
        if not assistant_created_at:
            from datetime import timedelta
            assistant_timestamp = user_timestamp + timedelta(seconds=1)
        else:
            assistant_timestamp = assistant_created_at
        
        messages = [
            {
                "role": "user",
                "content": user_message,
                "created_at": user_timestamp
            },
            {
                "role": "assistant",
                "content": assistant_message,
                "created_at": assistant_timestamp
            }
        ]
        
        return await self.add_messages_to_thread(
            user_id=user_id,
            user_name=user_name,
            messages=messages
        )
        
    async def get_user_context(self, user_id: str, message_count: int = 0) -> Optional[str]:
        try:
            thread_id = self._get_thread_id(user_id)
            
            # Ensure context template exists (idempotent)
            # This template defines how memory is structured when retrieved
            # Use async method with retry logic for 503 errors
            await self.ensure_context_template()

            # Get memory (context block) using custom template
            # Use run_in_executor to avoid blocking the event loop - makes LLM respond faster
            memory = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: self.client.thread.get_user_context(
                    thread_id=thread_id,
                    template_id=self.CONTEXT_TEMPLATE_ID  # Template used here to format memory
                )
            )

            if not memory or not memory.context:
                self.logger.debug(f"[Zep] No memory context available for user_id={user_id}, thread_id={thread_id}")
                return None

            context = memory.context

            # Log memory retrieval (debug level only to reduce latency)
            self.logger.debug(f"[Zep] Memory retrieved: {len(context)} chars for user_id={user_id}, thread_id={thread_id}")
            
            return context

        except Exception as e:
            error_str = str(e)
            # Handle 404 errors gracefully - thread doesn't exist yet (expected for new users)
            if "404" in error_str or "not found" in error_str.lower():
                if "template" in error_str.lower():
                    self.logger.debug(f"[Zep] Template {self.CONTEXT_TEMPLATE_ID} not found for user {user_id} - will use default context or retry template creation later")
                else:
                    self.logger.debug(f"[Zep] Thread {self._get_thread_id(user_id)} not found for user {user_id} - memory will be available after first message")
                return None
            # Handle 503 errors 
            if "503" in error_str or "temporarily unavailable" in error_str.lower():
                self.logger.debug(f"[Zep] Zep service temporarily unavailable (503) when retrieving memory for user {user_id}")
                return None
            # For other errors, log as debug (not warning) since memory retrieval is optional
            self.logger.debug(f"[Zep] Failed to retrieve memory for user {user_id}: {type(e).__name__}")
            return None
