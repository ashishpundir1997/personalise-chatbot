# app/llm/service/provider/openai_provider.py
from typing import AsyncGenerator, Optional
from openai import AsyncOpenAI
from app.core.config import settings

class OpenAIProvider:
    name = "openai"

    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.client = AsyncOpenAI(api_key=self.api_key) if self.api_key else None
        self._enabled = bool(self.api_key)

    def is_enabled(self) -> bool:
        return self._enabled

    async def generate(self, prompt: str = "", stream: bool = False, model: str = "gpt-4o-mini", temperature: float = 0.7, max_tokens: int = 512):
        if not self.is_enabled():
            raise RuntimeError("OpenAI disabled: missing API key")

        messages = [{"role": "user", "content": prompt}]

        if stream:
            async def stream_gen() -> AsyncGenerator[str, None]:
                try:
                    response_stream = await self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=True,
                    )
                    async for event in response_stream:
                        # adapt to the SDK event shape: delta content might be in event.choices[0].delta.content
                        delta = getattr(event.choices[0].delta, "content", None) if getattr(event, "choices", None) else None
                        if delta:
                            yield delta
                except Exception as e:
                    # bubble error to router so router can skip provider
                    raise e
            return stream_gen()
        else:
            resp = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )
            return resp.choices[0].message.content or ""
