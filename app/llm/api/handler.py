import json
from fastapi import HTTPException
from typing import AsyncGenerator
from app.chat.api.dto import ChatRequest, ChatResponse
from app.llm.api.dto import ProviderInfo, ProviderListResponse
from app.llm.service.router_service import LatencyRouter
from app.llm.service.llm_service import LLMService
from app.core.logger import get_logger

# Initialize shared router instance
router_instance = LatencyRouter()
logger = get_logger("ChatHandler")


class LLMHandler:
    """Handler for LLM API endpoints."""

    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service
        self.router = llm_service.router

    async def health(self) -> dict:
        """Health check for active providers."""
        active = [p for p in self.router.providers if getattr(p, "is_enabled", lambda: True)()]
        return {
            "status": "ok",
            "active_providers": len(active),
            "total_providers": len(self.router.providers)
        }

    async def providers(self) -> ProviderListResponse:
        """Return list of active and available providers."""
        provider_list = []
        for provider in self.router.providers:
            is_enabled = getattr(provider, "is_enabled", lambda: True)()
            latency = self.router.provider_latency.get(provider.name)
            provider_list.append(ProviderInfo(
                name=provider.name,
                latency_ms=int(latency * 1000) if latency else None,
                status="active" if is_enabled else "disabled"
            ))
        return ProviderListResponse(providers=provider_list)


async def handle_chat(body: ChatRequest) -> ChatResponse:
    """Handles a non-streaming chat request."""
    try:
        # Build a prompt from messages (use last user message by default)
        prompt = next((m.content for m in reversed(body.messages) if m.role == "user"),
                      body.messages[-1].content if body.messages else "")

        logger.debug(f"handle_chat start | model={body.model} temp={body.temperature} max_tokens={body.max_tokens}")
        response = await router_instance.generate({
            "prompt": prompt,
            "stream": False,
            "model": body.model,
            "temperature": body.temperature,
            "max_tokens": body.max_tokens,
        })

        text = response.get("text", "") if isinstance(response, dict) else str(response)
        logger.debug("handle_chat success")
        return ChatResponse(text=text, provider="router")

    except Exception as e:
        logger.error(f"handle_chat error | error={e}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")


async def handle_chat_stream(body: ChatRequest) -> AsyncGenerator[str, None]:
    """
    Handles a streaming chat request with structured SSE events:
    - If provider emits raw SSE events (lines starting with 'event:'), pass through.
    - Otherwise wrap plain text into content_block_delta events containing text_delta JSON.
    """
    try:
        # Extract the latest user prompt
        prompt = next(
            (m.content for m in reversed(body.messages) if m.role == "user"),
            body.messages[-1].content if body.messages else ""
        )

        logger.debug(f"handle_chat_stream start | model={body.model} temp={body.temperature} max_tokens={body.max_tokens}")

        # Ask the router for a streaming generator
        response = await router_instance.generate({
            "prompt": prompt,
            "stream": True,
            "model": body.model,
            "temperature": body.temperature,
            "max_tokens": body.max_tokens,
        })

        # Normalize to async generator
        async def to_async_gen(obj):
            if hasattr(obj, "__aiter__"):
                async for item in obj:
                    yield item
                return
            if isinstance(obj, dict):
                inner = obj.get("text")
                if hasattr(inner, "__aiter__"):
                    async for item in inner:
                        yield item
                    return
                if inner is not None:
                    yield str(inner)
                    return
            yield str(obj)

        yielded_any = False
        provider_emitted_complete = False
        provider_emitted_done = False

        async for chunk in to_async_gen(response):
            # normalize chunk to string and strip trailing/leading whitespace for checks
            text_piece = str(chunk)
            stripped = text_piece.lstrip()

            # If provider already emits SSE event lines, pass through raw
            if stripped.startswith("event:"):
                # mark if provider already emitted completion/done
                lower = stripped.lower()
                if "event: complete" in lower:
                    provider_emitted_complete = True
                if "event: done" in lower:
                    provider_emitted_done = True

                # yield provider event block unchanged (ensure double newline)
                # chunk may already include trailing newlines; ensure SSE framing
                if not text_piece.endswith("\n\n"):
                    yield text_piece + "\n\n"
                else:
                    yield text_piece
                yielded_any = True
                continue

            # If provider emitted raw "data: " style lines (SSE data) — pass through likewise
            if stripped.startswith("data:"):
                if not text_piece.endswith("\n\n"):
                    yield text_piece + "\n\n"
                else:
                    yield text_piece
                yielded_any = True
                continue

            # Otherwise wrap plain text as a content_block_delta / text_delta for frontend
            event_data = json.dumps({"type": "text_delta", "text": text_piece})
            yield f"event: content_block_delta\ndata: {event_data}\n\n"
            yielded_any = True

        # If nothing streamed from provider, fallback to non-streaming once
        if not yielded_any:
            logger.debug("handle_chat_stream produced no chunks; fallback to non-stream")
            try:
                fallback = await router_instance.generate({
                    "prompt": prompt,
                    "stream": False,
                    "model": body.model,
                    "temperature": body.temperature,
                    "max_tokens": body.max_tokens,
                })
                text = fallback.get("text", "") if isinstance(fallback, dict) else str(fallback)
                if text:
                    event_data = json.dumps({"type": "text_delta", "text": text})
                    yield f"event: content_block_delta\ndata: {event_data}\n\n"
            except Exception as fe:
                logger.error(f"handle_chat_stream fallback error | {fe}")

        # If provider did not emit 'complete' or 'done', send them
        if not provider_emitted_complete:
            yield "event: complete\ndata: {}\n\n"
        if not provider_emitted_done:
            yield "event: done\ndata: {}\n\n"

    except Exception as e:
        logger.error(f"handle_chat_stream error | {e}")
        error_data = json.dumps({"error": str(e)})
        yield f"event: error\ndata: {error_data}\n\n"
