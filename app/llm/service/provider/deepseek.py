# app/llm/service/providers/deepseek_provider.py
from openai import AsyncOpenAI
from typing import AsyncGenerator
from .base_provider import BaseProvider
from app.core.config import settings

class DeepSeekProvider(BaseProvider):
    """Handles DeepSeek API integration."""

    def __init__(self):
        self.api_key = settings.DEEPSEEK_API_KEY
        # Use OpenAI-compatible client against DeepSeek base_url
        base = settings.DEEPSEEK_BASE_URL or "https://api.deepseek.com/v1"
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=base)
        self.name = "deepseek"
        self._enabled = bool(self.api_key)

    async def generate(self, prompt: str, stream: bool = False, model: str = "deepseek-chat", **kwargs):
        if not self._enabled:
            raise RuntimeError("DeepSeek provider disabled: missing DEEPSEEK_API_KEY")

        # Normalize model to DeepSeek space if caller passed another provider's model
        effective_model = model if (isinstance(model, str) and model.startswith("deepseek")) else (getattr(settings, "DEEPSEEK_MODEL", None) or "deepseek-chat")

        if stream:
            async def stream_gen() -> AsyncGenerator[str, None]:
                stream = await self.client.chat.completions.create(
                    model=effective_model,
                    messages=[{"role": "user", "content": prompt}],
                    stream=True,
                    **kwargs,
                )
                async for chunk in stream:
                    delta = getattr(chunk.choices[0].delta, "content", None)
                    if delta:
                        yield delta
            return self.stream_response(stream_gen())
        else:
            response = await self.client.chat.completions.create(
                model=effective_model,
                messages=[{"role": "user", "content": prompt}],
                **kwargs,
            )
            return response.choices[0].message.content

    def is_enabled(self) -> bool:
        return self._enabled
