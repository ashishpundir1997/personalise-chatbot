# app/llm/service/router_service.py
import asyncio
import json
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Callable
from app.core.logger import get_logger

logger = get_logger("LatencyRouter")


class LatencyRouter:
    """
    Central routing layer for LLM requests.
    Handles provider selection (primary, hedge, fastest) and
    streams structured Server-Sent Events (SSE).
    """

    def __init__(
        self,
        providers: Optional[List[Any]] = None,
        routing_strategy: str = "primary",
        request_timeout_ms: int = 45000,
        hedge_delay_ms: int = 250,
    ):
        from app.llm.service.provider.openai_provider import OpenAIProvider
        from app.llm.service.provider.gemini import GeminiProvider
        from app.llm.service.provider.deepseek import DeepSeekProvider
        from app.llm.service.provider.anthropic import AnthropicProvider
        from app.llm.service.provider.oolama import OllamaProvider

        self.providers = providers or [
            GeminiProvider(),
            # OpenAIProvider(),
            # DeepSeekProvider(),
            # AnthropicProvider(),
            # OllamaProvider(),
        ]
        self.routing_strategy = routing_strategy
        self.request_timeout_ms = request_timeout_ms
        self.hedge_delay_ms = hedge_delay_ms
        self.provider_latency: Dict[str, float] = {}

    async def _with_timeout(self, coro, timeout_ms: int):
        """Helper to apply timeout."""
        try:
            return await asyncio.wait_for(coro, timeout_ms / 1000)
        except asyncio.TimeoutError:
            raise Exception("Timeout")

    async def _sleep(self, ms: int):
        await asyncio.sleep(ms / 1000)

    async def _first_fulfilled(self, tasks: List[asyncio.Task]):
        """Return first successfully completed task (like Promise.any)."""
        errors = 0
        for task in asyncio.as_completed(tasks):
            try:
                return await task
            except Exception:
                errors += 1
                if errors == len(tasks):
                    raise Exception("All providers failed")

    async def generate(
        self,
        params: Dict[str, Any],
    ) -> Dict[str, Any] | AsyncGenerator[str, None]:
        """
        Main generate function.
        If stream=True, yields **SSE-formatted** events like:
          event: content_block_delta
          data: {"type": "text_delta", "text": "Hel"}

        If stream=False, returns dict {text, provider}.
        """
        all_providers = list(self.providers)
        active = [p for p in all_providers if getattr(p, "is_enabled", lambda: True)()]
        if not active:
            raise Exception("No providers available")

        stream = params.get("stream", False)
        model = params.get("model")

        async def call_provider(provider):
            """Simple wrapper for non-streaming call."""
            start = time.perf_counter()
            result = await self._with_timeout(provider.generate(**params), self.request_timeout_ms)
            self.provider_latency[provider.name] = time.perf_counter() - start
            return {"text": result, "provider": provider.name}

        if stream:
            async def stream_fallback_gen() -> AsyncGenerator[str, None]:
                last_error: Optional[Exception] = None
                for provider in active:
                    try:
                        start = time.perf_counter()
                        gen = await self._with_timeout(provider.generate(**params), self.request_timeout_ms)

                        # SSE event: stream started
                        yield f"event: start\ndata: {json.dumps({'provider': provider.name})}\n\n"

                        # Detect async generator
                        if hasattr(gen, "__aiter__"):
                            first_yielded = False
                            async for chunk in gen:
                                if not first_yielded:
                                    self.provider_latency[provider.name] = time.perf_counter() - start
                                    first_yielded = True
                                # Emit chunk as SSE event
                                if chunk:
                                    payload = {"type": "text_delta", "text": chunk}
                                    yield f"event: content_block_delta\ndata: {json.dumps(payload)}\n\n"

                            # After stream completion
                            yield "event: complete\ndata: {}\n\n"
                            return

                        else:
                            # If provider returned a full string (not generator), emit in small deltas
                            full_text = str(gen)
                            def _split_text_words(txt: str, max_len: int = 40):
                                words = txt.split()
                                buf = []
                                current = ""
                                for w in words:
                                    if not current:
                                        candidate = w
                                    else:
                                        candidate = current + " " + w
                                    if len(candidate) <= max_len:
                                        current = candidate
                                    else:
                                        if current:
                                            buf.append(current)
                                        current = w
                                if current:
                                    buf.append(current)
                                return buf
                            for piece in _split_text_words(full_text):
                                payload = {"type": "text_delta", "text": piece}
                                yield f"event: content_block_delta\ndata: {json.dumps(payload)}\n\n"
                            yield "event: complete\ndata: {}\n\n"
                            return

                    except Exception as e:
                        logger.error(f"Provider {provider.name} stream failed: {e}")
                        last_error = e
                        yield f"event: error\ndata: {json.dumps({'error': str(e), 'provider': provider.name})}\n\n"
                        continue

                yield f"event: error\ndata: {json.dumps({'error': 'All providers failed'})}\n\n"
                raise Exception(f"All providers failed: {last_error}")

            return {"text": stream_fallback_gen(), "provider": "router"}

        for provider in active:
            try:
                return await call_provider(provider)
            except Exception as e:
                logger.error(f"Provider failed: {provider.name} — {e}")
                continue
        raise Exception("All providers failed")

    async def stream_generate(self, params: Dict[str, Any], on_chunk: Callable[[str], Any]):
        """
        Alternative callback-based streaming.
        Calls `on_chunk(sse_event)` for each structured SSE line.
        """
        active = [p for p in self.providers if getattr(p, "is_enabled", lambda: True)()]
        if not active:
            await on_chunk("event: error\ndata: {\"error\": \"No providers available\"}\n\n")
            return

        for provider in active:
            try:
                gen = await self._with_timeout(provider.generate(**{**params, "stream": True}), self.request_timeout_ms)
                await on_chunk(f"event: start\ndata: {{\"provider\": \"{provider.name}\"}}\n\n")

                if hasattr(gen, "__aiter__"):
                    async for chunk in gen:
                        event = {
                            "type": "text_delta",
                            "text": chunk,
                        }
                        await on_chunk(f"event: content_block_delta\ndata: {json.dumps(event)}\n\n")

                await on_chunk("event: complete\ndata: {}\n\n")
                return

            except Exception as e:
                logger.error(f"Provider {provider.name} failed: {e}")
                await on_chunk(f"event: error\ndata: {{\"error\": \"{str(e)}\", \"provider\": \"{provider.name}\"}}\n\n")
                continue

        await on_chunk("event: error\ndata: {\"error\": \"All providers failed\"}\n\n")

    def get_latency_report(self) -> Dict[str, float]:
        return self.provider_latency

    def __repr__(self):
        return f"<LatencyRouter strategy={self.routing_strategy}>"
