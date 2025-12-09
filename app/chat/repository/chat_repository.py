# app/chat/repository/chat_repository.py

from typing import Optional, List
from uuid import UUID
from sqlalchemy.future import select
from sqlalchemy import delete
from datetime import datetime

from app.chat.entity.chat import Conversation, Message, MessageRole
from app.chat.repository.sql_schema.conversation import ConversationModel, MessageModel
from app.chat.service.service import IChatRepository
from pkg.db_util.postgres_conn import PostgresConnection
from pkg.log.logger import get_logger

logger = get_logger(__name__)


class ChatRepository(IChatRepository):
    """Handles all database interactions for chat conversations and messages."""

    def __init__(self, postgres: PostgresConnection):
        self.postgres = postgres
        self.logger = logger

    # ────────────────────────────────────────────────
    # Conversation CRUD
    # ────────────────────────────────────────────────

    async def save_conversation(self, user_id: str, conversation: Conversation) -> str:
        """Save a new conversation to Postgres."""
        async with self.postgres.get_session() as session:
            now = datetime.utcnow()
            new_conv = ConversationModel(
                id=conversation.conversation_id,
                user_id=user_id,
                created_at=conversation.created_at or now,
                last_activity=conversation.last_activity or now,
                message_count=conversation.message_count or 0,
            )
            session.add(new_conv)
            await session.commit()
            self.logger.info(f"Conversation saved: {new_conv.id}")
            return str(new_conv.id)

    async def get_conversation(
        self,
        user_id: str,
        conversation_id: UUID,
        include_messages: bool = True,
        page: int = 1,
        page_size: int = 100000
    ) -> Optional[Conversation]:
        """Fetch a conversation and optionally its messages."""
        async with self.postgres.get_session() as session:
            result = await session.execute(
                select(ConversationModel).where(ConversationModel.id == conversation_id)
            )
            conv = result.scalar_one_or_none()
            if not conv:
                return None

            conversation = Conversation(
                conversation_id=str(conv.id),
                user_id=conv.user_id,
                created_at=conv.created_at.isoformat(),
                last_activity=conv.last_activity.isoformat(),
                message_count=conv.message_count,
                messages=[],
            )

            if include_messages:
                result_msgs = await session.execute(
                    select(MessageModel)
                    .where(MessageModel.conversation_id == conv.id)
                    .order_by(MessageModel.created_at.asc())
                )
                msgs = result_msgs.scalars().all()
                conversation.messages = [
                    Message(
                        role=m.sender_role,
                        content=m.content,
                        created_at=m.created_at.isoformat(),
                        metadata=m.message_metadata or {},
                    )
                    for m in msgs
                ]

            return conversation

    async def list_conversations(self, user_id: str, pal: str = None) -> List[Conversation]:
        """List all conversations for a given user."""
        async with self.postgres.get_session() as session:
            result = await session.execute(
                select(ConversationModel)
                .where(ConversationModel.user_id == user_id)
                .order_by(ConversationModel.last_activity.desc())
            )
            convs = result.scalars().all()
            return [
                Conversation(
                    conversation_id=str(c.id),
                    user_id=c.user_id,
                    created_at=c.created_at.isoformat(),
                    last_activity=c.last_activity.isoformat(),
                    message_count=c.message_count,
                )
                for c in convs
            ]

    async def delete_conversation(self, conversation_id: UUID, user_id: str):
        """Delete a conversation and all its messages."""
        async with self.postgres.get_session() as session:
            await session.execute(
                delete(MessageModel).where(MessageModel.conversation_id == conversation_id)
            )
            await session.execute(
                delete(ConversationModel).where(ConversationModel.id == conversation_id)
            )
            await session.commit()
            self.logger.info(f"Deleted conversation {conversation_id}")

    # ────────────────────────────────────────────────
    # Message CRUD
    # ────────────────────────────────────────────────

    async def save_message(self, user_id: str, message: Message) -> str:
        """Save a new message under a conversation."""
        async with self.postgres.get_session() as session:
            now = datetime.utcnow()
            new_msg = MessageModel(
                conversation_id=message.metadata.get("conversation_id"),
                sender_role=message.role,
                content=message.content,
                message_metadata=message.metadata or {},
                created_at=message.created_at or now,
            )
            session.add(new_msg)

            # Update conversation's message_count and last_activity
            await session.execute(
                select(ConversationModel)
                .where(ConversationModel.id == message.metadata.get("conversation_id"))
            )
            await session.commit()
            self.logger.debug(f"Message saved for conversation {message.metadata.get('conversation_id')}")
            return str(new_msg.id)

    async def get_message(self, user_id: str, message_id: UUID) -> Optional[Message]:
        """Retrieve a single message by its ID."""
        async with self.postgres.get_session() as session:
            result = await session.execute(
                select(MessageModel).where(MessageModel.id == message_id)
            )
            msg = result.scalar_one_or_none()
            if not msg:
                return None

            return Message(
                role=msg.sender_role,
                content=msg.content,
                created_at=msg.created_at.isoformat(),
                metadata=msg.message_metadata or {},
            )

