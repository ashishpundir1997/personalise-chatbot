from abc import ABC, abstractmethod
from typing import Optional, List, Tuple, AsyncGenerator, Dict, Any
from app.chat.entity.chat import Conversation, Message
from uuid import UUID


class IChatRepository(ABC):
    @abstractmethod
    async def save_conversation(self, user_id: str, conversation: Conversation) -> str:
        pass

    @abstractmethod
    async def save_message(self, user_id: str, message: Message) -> str:
        pass

    @abstractmethod
    async def get_conversation(self, user_id: str, conversation_id: UUID, include_messages: bool = True,
                               page: int = 1, page_size: int = 100000) -> Optional[Conversation]:
        pass

    @abstractmethod
    async def list_conversations(self, user_id: str, pal: str = None) -> List[Conversation]:
        pass

    @abstractmethod
    async def delete_conversation(self, conversation_id: UUID, user_id: str):
        pass

    @abstractmethod
    async def get_message(self,user_id: str, message_id: UUID) -> Message:
        pass



