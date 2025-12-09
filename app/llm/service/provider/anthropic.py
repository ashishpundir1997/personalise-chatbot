# app/llm/service/providers/anthropic_provider.py
from anthropic import AsyncAnthropic
from .base_provider import BaseProvider
from app.core.config import settings

class AnthropicProvider(BaseProvider):
    """Handles Claude (Anthropic) models."""

    def __init__(self):
        self.name = "anthropic"
        self.api_key = settings.ANTHROPIC_API_KEY
        self.client = AsyncAnthropic(api_key=self.api_key) if self.api_key else None
        self._enabled = bool(self.api_key)

    async def generate(self, prompt: str, stream: bool = False, model: str = "claude-3-7-sonnet", **kwargs):
        if not self._enabled:
            raise RuntimeError("Anthropic provider disabled: missing ANTHROPIC_API_KEY")
        if stream:
            async def stream_gen():
                async with self.client.messages.stream(
                    model=model,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                ) as s:
                    async for event in s:
                        if getattr(event, "type", None) == "message_delta" and getattr(event, "delta", None) and getattr(event.delta, "text", None):
                            yield event.delta.text
            return self.stream_response(stream_gen())
        else:
            msg = await self.client.messages.create(
                model=model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text

    def is_enabled(self) -> bool:
        return self._enabled
