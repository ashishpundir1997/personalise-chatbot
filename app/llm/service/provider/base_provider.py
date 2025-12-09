# app/llm/service/providers/base_provider.py
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any


class BaseProvider(ABC):
    """Abstract base provider for all LLM integrations."""

    @abstractmethod
    async def generate(self, prompt: str, stream: bool = False, **kwargs) -> Any:
        """Generate response from model."""
        pass

    async def stream_response(self, response_gen: AsyncGenerator[str, None]):
        """Utility for streaming token-by-token responses."""
        async for chunk in response_gen:
            yield chunk

    def is_enabled(self) -> bool:
        """Whether this provider is enabled/usable (e.g., API key present)."""
        return True
