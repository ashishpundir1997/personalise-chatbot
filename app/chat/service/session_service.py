import os
import uuid
import json
from datetime import datetime
from typing import List, Dict, Optional, Any

from sqlalchemy import text

from pkg.log.logger import get_logger
from pkg.db_util.postgres_conn import PostgresConnection
from pkg.db_util.types import PostgresConfig
from pkg.redis.client import RedisClient

logger = get_logger(__name__)


class ConversationManager:
    """
    Conversation manager using:
    - Redis → Fast caching for active conversation & recent messages.
    - Postgres → Persistent storage for all messages & metadata.
    """

    REDIS_TTL = 7 * 24 * 60 * 60       # Cache TTL: 7 days
    MAX_CACHED_MESSAGES = 100          # Keep last 100 messages in Redis (matches handler limit)

    def __init__(self, redis_client: Optional[RedisClient] = None, postgres_conn: Optional[PostgresConnection] = None):
        # Use provided PostgresConnection or create a new one (for backward compatibility)
        if postgres_conn is not None:
            self.postgres = postgres_conn
        else:
            # Fallback: create PostgresConnection if not provided (for backward compatibility)
            self.postgres = PostgresConnection(
                PostgresConfig(
                    host=os.getenv("POSTGRES_HOST", "localhost"),
                    port=int(os.getenv("POSTGRES_PORT", "5432")),
                    username=os.getenv("POSTGRES_USER", "postgres"),
                    password=os.getenv("POSTGRES_PASSWORD", "password"),
                    database=os.getenv("POSTGRES_DB", "neo_chat_db"),
                ),
                logger,
            )

        # Use provided RedisClient or create a new one
        if redis_client is not None:
            self.redis_client = redis_client
        else:
            # Fallback: create RedisClient if not provided (for backward compatibility)
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            redis_password = os.getenv("REDIS_PASSWORD") or None
            self.redis_client = RedisClient(logger, host=redis_host, port=redis_port, password=redis_password)

        self._schema_checked = False

    async def _ensure_schema(self):
        if self._schema_checked:
            return
        try:
            async with self.postgres.get_session() as session:
                await session.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS name VARCHAR(255)"))
                await session.commit()
            self._schema_checked = True
        except Exception as e:
            logger.error(f"Schema ensure failed for conversations.name: {e}")


    # Helper Key Builders

    def _conversation_key(self, conversation_id: str) -> str:
        return f"conversation:{conversation_id}"

    def _messages_key(self, conversation_id: str) -> str:
        return f"conversation:{conversation_id}:messages"

    # ----------------------------
    # Lifecycle Methods
    # ----------------------------
    async def create_conversation(self, user_id: str) -> str:
        """Create a new conversation (Redis + Postgres)."""
        await self._ensure_schema()
        conversation_id = str(uuid.uuid4())
        now = datetime.utcnow()

        data = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "created_at": now.isoformat(),
            "last_activity": now.isoformat(),
            "message_count": 0,
        }

        await self.redis_client.async_set_value(self._conversation_key(conversation_id), data, expiry=self.REDIS_TTL)
        await self.redis_client.async_set_value(self._messages_key(conversation_id), [], expiry=self.REDIS_TTL)

        async with self.postgres.get_session() as session:
            await session.execute(
                text("""
                    INSERT INTO conversations (id, user_id, created_at, last_activity, message_count, name)
                    VALUES (:id, :user_id, :created_at, :last_activity, :message_count, :name)
                """),
                {
                    "id": conversation_id,
                    "user_id": user_id,
                    "created_at": now,
                    "last_activity": now,
                    "message_count": 0,
                    "name": None,
                },
            )
            await session.commit()

        return conversation_id

    async def has_title_generated(self, conversation_id: str) -> bool:
        """
        Check if a conversation has a real title generated (not null and not "New Chat").
        This is used internally to determine if title generation should run.
        Returns True if a real title exists, False if title is null or "New Chat".
        Always checks the database to get the true value, not the cached default.
        """
        try:
            uuid.UUID(conversation_id)
        except (ValueError, TypeError):
            return False
        
        # Always check database for the true value (cache might have "New Chat" as default)
        async with self.postgres.get_session() as session:
            result = await session.execute(
                text("SELECT name FROM conversations WHERE id = :id"),
                {"id": conversation_id},
            )
            row = result.fetchone()
            if not row:
                return False
            
            raw_title = row[0]
            # Return True only if title exists and is not "New Chat"
            # None or empty string means no title generated
            return bool(raw_title and raw_title.strip() and raw_title != "New Chat")

    async def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve conversation metadata from Redis → fallback Postgres."""
        # Validate UUID format before querying
        try:
            uuid.UUID(conversation_id)
        except (ValueError, TypeError):
            # Log at debug level for common placeholder values, warning for others
            if conversation_id.lower() in ("string", "null", "none", ""):
                logger.debug(f"Invalid conversation_id format (placeholder): {conversation_id}")
            else:
                logger.warning(f"Invalid conversation_id format: {conversation_id}")
            return None
        
        cached = await self.redis_client.async_get_value(self._conversation_key(conversation_id))
        if cached:
            # cached is already deserialized by async_get_value
            conv_data = cached if isinstance(cached, dict) else json.loads(cached) if isinstance(cached, str) else {}
            # Migrate old cached data from updated_at to last_activity
            if "updated_at" in conv_data and "last_activity" not in conv_data:
                conv_data["last_activity"] = conv_data.pop("updated_at")
                # Update cache with migrated data
                await self.redis_client.async_set_value(self._conversation_key(conversation_id), conv_data, expiry=self.REDIS_TTL)
            # Map 'name' to 'title' for response (keep 'name' for backward compatibility)
            # Always ensure both 'title' and 'name' are present and synced
            # Use "New Chat" as default if title is null
            if "name" in conv_data:
                if "title" not in conv_data or conv_data["title"] != conv_data["name"]:
                    conv_data["title"] = conv_data["name"] if conv_data["name"] else "New Chat"
            elif "title" in conv_data:
                # If title exists but name doesn't, sync them
                conv_data["name"] = conv_data["title"] if conv_data["title"] else "New Chat"
            else:
                # Neither exists, set both to "New Chat"
                conv_data["title"] = "New Chat"
                conv_data["name"] = "New Chat"
            
            # Ensure title is never null - default to "New Chat"
            if not conv_data.get("title"):
                conv_data["title"] = "New Chat"
            if not conv_data.get("name"):
                conv_data["name"] = "New Chat"
            
            return conv_data

        async with self.postgres.get_session() as session:
            result = await session.execute(
                text("SELECT id, user_id, created_at, last_activity, message_count, name FROM conversations WHERE id = :id"),
                {"id": conversation_id},
            )
            row = result.fetchone()
            if not row:
                return None

            # Convert UUID to string for JSON serialization
            conv_id = str(row[0]) if row[0] else None
            
            # Use "New Chat" as default if title is null
            title_value = row[5] if row[5] else "New Chat"
            conv = {
                "conversation_id": conv_id,
                "user_id": row[1],
                "created_at": row[2].isoformat() if row[2] else None,
                "last_activity": row[3].isoformat() if row[3] else None,
                "message_count": row[4],
                "title": title_value,  # Map database 'name' column to 'title' in response, default to "New Chat"
                "name": title_value,  # Keep 'name' for backward compatibility with DB column
            }

            await self.redis_client.async_set_value(self._conversation_key(conversation_id), conv, expiry=self.REDIS_TTL)
            return conv

    async def add_message(self, conversation_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """Add a message to both Postgres + Redis (limited cache)."""
        await self._ensure_schema()
        now = datetime.utcnow()
        msg = {
            "role": role,
            "content": content,
            "created_at": now.isoformat(),
            "metadata": metadata or {},
        }

        # Update cached messages — only keep last N
        cached_msgs = await self.redis_client.async_get_value(self._messages_key(conversation_id), default=[])
        msgs = cached_msgs if isinstance(cached_msgs, list) else (json.loads(cached_msgs) if isinstance(cached_msgs, str) else [])
        msgs.append(msg)
        if len(msgs) > self.MAX_CACHED_MESSAGES:
            msgs = msgs[-self.MAX_CACHED_MESSAGES:]
        await self.redis_client.async_set_value(self._messages_key(conversation_id), msgs, expiry=self.REDIS_TTL)

        # Persist in Postgres
        message_id = str(uuid.uuid4())
        async with self.postgres.get_session() as session:
            await session.execute(
                text("""
                    INSERT INTO messages (id, conversation_id, sender_role, content, message_metadata, created_at)
                    VALUES (:id, :conversation_id, :sender_role, :content, :message_metadata, :created_at)
                """),
                {
                    "id": message_id,
                    "conversation_id": conversation_id,
                    "sender_role": role,
                    "content": content,
                    "message_metadata": json.dumps(metadata or {}),
                    "created_at": now,
                },
            )

            await session.execute(
                text("UPDATE conversations SET message_count = message_count + 1, last_activity = :last_activity WHERE id = :id"),
                {"id": conversation_id, "last_activity": now},
            )
            await session.commit()
        
        # Update conversation cache in Redis with new last_activity
        cached_conv = await self.redis_client.async_get_value(self._conversation_key(conversation_id))
        if cached_conv:
            conv_data = cached_conv if isinstance(cached_conv, dict) else (json.loads(cached_conv) if isinstance(cached_conv, str) else {})
            conv_data["last_activity"] = now.isoformat()
            conv_data["message_count"] = conv_data.get("message_count", 0) + 1
            await self.redis_client.async_set_value(self._conversation_key(conversation_id), conv_data, expiry=self.REDIS_TTL)


    async def _check_has_more_messages(
        self, 
        conversation_id: str, 
        oldest_timestamp: datetime,
        session
    ) -> bool:
        """Helper to check if there are more messages older than the given timestamp."""
        try:
            check_result = await session.execute(
                text("""
                    SELECT 1
                    FROM messages
                    WHERE conversation_id = :conversation_id
                    AND created_at < :oldest_timestamp
                    LIMIT 1
                """),
                {
                    "conversation_id": conversation_id,
                    "oldest_timestamp": oldest_timestamp
                }
            )
            return check_result.fetchone() is not None
        except Exception as e:
            logger.warning(f"Error checking for more messages in DB: {e}, assuming no more")
            return False

    def _normalize_message(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize message format to ensure consistent structure (identical for Redis and Postgres)."""
        return {
            "role": msg.get("role", msg.get("sender_role", "user")),
            "content": msg.get("content", ""),
            "metadata": msg.get("metadata", {}),
            "created_at": msg.get("created_at", "")
        }

    async def get_messages_paginated(
        self, 
        conversation_id: str, 
        limit: int = 25, 
        cursor: Optional[str] = None
    ) -> tuple[List[Dict[str, Any]], bool, Optional[str]]:
        """
        Get messages with cursor-based pagination.
        Returns: (messages, has_more, next_cursor)
        - If cursor is None: returns latest messages (from Redis if available, else Postgres)
        - If cursor is provided: returns messages older than cursor (always from Postgres)
        Both branches use identical logic for consistency.
        """
        from datetime import datetime
        
        # Parse cursor if provided
        cursor_timestamp = None
        if cursor:
            try:
                cursor_timestamp = datetime.fromisoformat(cursor.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                logger.warning(f"Invalid cursor format: {cursor}, ignoring cursor")
                cursor = None
        
        # If no cursor, try Redis first for latest messages (for performance)
        # But always validate and normalize to ensure identical behavior with Postgres
        if not cursor:
            cached_msgs = await self.redis_client.async_get_value(self._messages_key(conversation_id))
            if cached_msgs:
                msgs = cached_msgs if isinstance(cached_msgs, list) else (json.loads(cached_msgs) if isinstance(cached_msgs, str) else [])
                # Messages in Redis are stored chronologically (oldest first)
                # Return latest 'limit' messages (last N messages in the list)
                if len(msgs) <= limit:
                    # All cached messages fit in limit - return all
                    msgs_to_return = msgs
                else:
                    # Return latest 'limit' messages from cache (last N messages)
                    msgs_to_return = msgs[-limit:]
                
                # Normalize message format to match Postgres structure (identical format)
                normalized_msgs = [self._normalize_message(msg) for msg in msgs_to_return]
                
                # Use identical logic as Postgres branch for has_more and next_cursor
                has_more = False
                next_cursor = None
                
                if normalized_msgs:
                    oldest_msg = normalized_msgs[0]
                    oldest_timestamp_str = oldest_msg.get("created_at")
                    
                    # Check DB for messages older than the oldest cached message (same logic as Postgres)
                    if oldest_timestamp_str:
                        try:
                            oldest_timestamp = datetime.fromisoformat(oldest_timestamp_str.replace('Z', '+00:00'))
                            async with self.postgres.get_session() as session:
                                has_more = await self._check_has_more_messages(conversation_id, oldest_timestamp, session)
                        except Exception as e:
                            logger.warning(f"Error checking for more messages: {e}, assuming no more")
                            has_more = False
                    
                    # Only set next_cursor if there are more messages
                    if has_more:
                        next_cursor = oldest_timestamp_str
                
                return normalized_msgs, has_more, next_cursor
        
        # Fetch from Postgres (either cursor provided or cache miss)
        
        async with self.postgres.get_session() as session:
            if cursor_timestamp:
                # Fetch messages older than cursor
                result = await session.execute(
                    text("""
                        SELECT sender_role, content, message_metadata, created_at
                        FROM messages
                        WHERE conversation_id = :conversation_id
                        AND created_at < :cursor_timestamp
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    {
                        "conversation_id": conversation_id, 
                        "cursor_timestamp": cursor_timestamp,
                        "limit": limit
                    },
                )
            else:
                # Fetch latest messages
                result = await session.execute(
                    text("""
                        SELECT sender_role, content, message_metadata, created_at
                        FROM messages
                        WHERE conversation_id = :conversation_id
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    {"conversation_id": conversation_id, "limit": limit},
                )
            
            rows = result.fetchall()
            # Normalize messages to same format as Redis branch (identical structure)
            msgs = [
                self._normalize_message({
                    "role": r[0],
                    "content": r[1],
                    "metadata": json.loads(r[2]) if r[2] else {},
                    "created_at": r[3].isoformat(),
                })
                for r in rows
            ]
            # Reverse to get chronological order (oldest first) - same as Redis
            msgs.reverse()
            
            # Use identical logic as Redis branch for has_more and next_cursor
            has_more = False
            next_cursor = None
            
            if msgs:
                oldest_msg = msgs[0]
                oldest_timestamp_str = oldest_msg.get("created_at")
                
                # Check if there are more messages older than the oldest one (same helper as Redis branch)
                if oldest_timestamp_str:
                    try:
                        oldest_timestamp = datetime.fromisoformat(oldest_timestamp_str.replace('Z', '+00:00'))
                        has_more = await self._check_has_more_messages(conversation_id, oldest_timestamp, session)
                    except Exception as e:
                        logger.warning(f"Error checking for more messages: {e}, assuming no more")
                        has_more = False
                
                # Only set next_cursor if there are more messages
                if has_more:
                    next_cursor = oldest_timestamp_str
            
            return msgs, has_more, next_cursor

    async def rename_conversation(self, conversation_id: str, new_name: str) -> None:
        """Rename conversation - updates both Postgres and Redis cache."""
        await self._ensure_schema()
        
        # Validate conversation exists
        conv = await self.get_conversation(conversation_id)
        if not conv:
            raise ValueError(f"Conversation {conversation_id} not found")
        
        # Update in Postgres
        async with self.postgres.get_session() as session:
            await session.execute(
                text("UPDATE conversations SET name = :name WHERE id = :id"),
                {"id": conversation_id, "name": new_name}
            )
            await session.commit()
        
        # Update in Redis cache - always update to ensure consistency
        cached_conv = await self.redis_client.async_get_value(self._conversation_key(conversation_id))
        if cached_conv:
            conv_data = cached_conv if isinstance(cached_conv, dict) else (json.loads(cached_conv) if isinstance(cached_conv, str) else {})
            conv_data["title"] = new_name  # Map to 'title' in cache
            conv_data["name"] = new_name  # Keep 'name' for backward compatibility with DB column
            await self.redis_client.async_set_value(self._conversation_key(conversation_id), conv_data, expiry=self.REDIS_TTL)
        else:
            # Cache doesn't exist, but we should still create it to ensure consistency
            # Fetch the full conversation data and cache it
            full_conv = await self.get_conversation(conversation_id)
            if full_conv:
                # Ensure title and name are both set
                full_conv["title"] = new_name
                full_conv["name"] = new_name
                await self.redis_client.async_set_value(self._conversation_key(conversation_id), full_conv, expiry=self.REDIS_TTL)
        

    async def get_recent_messages(self, conversation_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Return last `limit` messages (Redis first, fallback to Postgres if limit exceeds cache)."""
        cached_msgs = await self.redis_client.async_get_value(self._messages_key(conversation_id))
        
        # If user requests more messages than what's cached in Redis, fetch from Postgres
        if cached_msgs:
            msgs = cached_msgs if isinstance(cached_msgs, list) else (json.loads(cached_msgs) if isinstance(cached_msgs, str) else [])
            cached_count = len(msgs)
            
            # If requested limit is within cached messages, return from cache (don't overwrite cache)
            if limit <= cached_count:
                msgs = msgs[-limit:]
                return msgs
        
        # Fetch from Postgres (either cache miss or insufficient cache)
        async with self.postgres.get_session() as session:
            result = await session.execute(
                text("""
                    SELECT sender_role, content, message_metadata, created_at
                    FROM messages
                    WHERE conversation_id = :conversation_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"conversation_id": conversation_id, "limit": limit},
            )
            rows = result.fetchall()
            msgs = [
                {
                    "role": r[0],
                    "content": r[1],
                    "metadata": json.loads(r[2]) if r[2] else {},
                    "created_at": r[3].isoformat(),
                }
                for r in rows
            ]
            msgs.reverse()

            # Only cache if:
            # 1. Cache is empty (cache miss), OR
            # 2. We fetched more messages than what's currently cached
            # This prevents overwriting a larger cache with fewer messages
            should_cache = True
            if cached_msgs:
                cached_count = len(cached_msgs) if isinstance(cached_msgs, list) else len(json.loads(cached_msgs) if isinstance(cached_msgs, str) else [])
                if len(msgs) <= cached_count:
                    should_cache = False
            
            if should_cache:
                # Cache for next time (but only cache up to MAX_CACHED_MESSAGES to avoid storing too much)
                msgs_to_cache = msgs[-self.MAX_CACHED_MESSAGES:] if len(msgs) > self.MAX_CACHED_MESSAGES else msgs
                await self.redis_client.async_set_value(self._messages_key(conversation_id), msgs_to_cache, expiry=self.REDIS_TTL)
            
            return msgs

    async def list_conversations(self, user_id: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """List recent conversations for a user ordered by last_activity desc, with pagination."""
        try:
            async with self.postgres.get_session() as session:
                result = await session.execute(
                text(
                    """
                        SELECT id, user_id, created_at, last_activity, message_count, name
                        FROM conversations
                        WHERE user_id = :user_id
                        ORDER BY last_activity DESC
                        LIMIT :limit OFFSET :offset
                        """
                    ),
                    {"user_id": user_id, "limit": limit, "offset": offset},
                )
                rows = result.fetchall()
                conversations: List[Dict[str, Any]] = []
                for r in rows:
                    # Use "New Chat" as default if title is null
                    title_value = r[5] if r[5] else "New Chat"
                    conversations.append(
                        {
                            "conversation_id": r[0],
                            "user_id": r[1],
                            "created_at": r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2]),
                            "last_activity": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3]),
                            "message_count": r[4],
                            "title": title_value,  # Map database 'name' column to 'title' in response, default to "New Chat"
                        }
                    )
                return conversations
        except Exception as e:
            logger.error(f"Error listing conversations for user_id={user_id}: {e}")
            return []

    async def delete_conversation(self, conversation_id: str):
        """Delete conversation + all related messages."""
        await self.redis_client.async_delete(self._conversation_key(conversation_id), self._messages_key(conversation_id))

        async with self.postgres.get_session() as session:
            await session.execute(text("DELETE FROM messages WHERE conversation_id = :conversation_id"), {"conversation_id": conversation_id})
            await session.execute(text("DELETE FROM conversations WHERE id = :conversation_id"), {"conversation_id": conversation_id})
            await session.commit()


    async def close(self):
        """shutdown of Redis + Postgres."""
        if self.redis_client:
            await self.redis_client.async_close()
        await self.postgres.close_engine()
        logger.info("ConversationManager closed: Redis pool and Postgres engine disconnected")