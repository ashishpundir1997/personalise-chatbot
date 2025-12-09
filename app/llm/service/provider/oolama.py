# app/llm/service/providers/ollama_provider.py
import httpx
from .base_provider import BaseProvider
from app.core.config import settings

class OllamaProvider(BaseProvider):
    """Handles Ollama (local models) interaction."""

    def __init__(self, base_url: str = None):
        self.base_url = base_url or (settings.OLLAMA_BASE_URL or "http://localhost:11434")
        self.name = "ollama"

    async def generate(self, prompt: str, stream: bool = False, model: str = "llama3", **kwargs):
        payload = {"model": model, "prompt": prompt, "stream": stream, **kwargs}
        async with httpx.AsyncClient() as client:
            if stream:
                async def stream_gen():
                    async with client.stream("POST", f"{self.base_url}/api/generate", json=payload) as r:
                        async for line in r.aiter_lines():
                            if line:
                                yield line
                return self.stream_response(stream_gen())
            else:
                response = await client.post(f"{self.base_url}/api/generate", json=payload)
                return response.json().get("response", "")

    def is_enabled(self) -> bool:
        """Enable only if explicitly opted in via env to avoid accidental failures."""
        import os
        return os.getenv("OLLAMA_ENABLED", "false").lower() in ("1", "true", "yes")
