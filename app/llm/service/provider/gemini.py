import httpx
import json
from typing import AsyncGenerator
from .base_provider import BaseProvider
from app.core.config import settings
from app.core.logger import get_logger

class GeminiProvider(BaseProvider):
    """Handles Google Gemini models."""

    def __init__(self):
        self.name = "gemini"
        self.api_key = settings.GEMINI_API_KEY
        self.endpoint = (settings.GEMINI_FREE_ENDPOINT or "https://generativelanguage.googleapis.com").rstrip("/")
        self._enabled = bool(self.api_key)
        self._logger = get_logger("GeminiProvider")

    def is_enabled(self) -> bool:
        return self._enabled

    async def generate(
        self,
        prompt: str,
        stream: bool = False,
        model: str = "gemini-2.0-flash-exp",
        **kwargs,
    ) -> AsyncGenerator[str, None] | str:
        if not self._enabled:
            raise RuntimeError("Gemini provider disabled: missing GEMINI_API_KEY")

        effective_model = model if model.startswith("gemini") else "gemini-2.0-flash-exp"
        base_url = f"{self.endpoint}/v1beta/models/{effective_model}"
        # Include generation config if provided
        temperature = kwargs.get("temperature")
        max_tokens = kwargs.get("max_tokens") or kwargs.get("max_output_tokens")
        generation_config = {}
        if temperature is not None:
            generation_config["temperature"] = float(temperature)
        if max_tokens is not None:
            try:
                generation_config["maxOutputTokens"] = int(max_tokens)
            except Exception:
                pass

        payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if generation_config:
            payload["generationConfig"] = generation_config

        if stream:
            async def stream_gen() -> AsyncGenerator[str, None]:
                url = f"{base_url}:streamGenerateContent?key={self.api_key}"
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("POST", url, json=payload) as resp:
                        if resp.status_code != 200:
                            self._logger.error(f"Gemini API error: status={resp.status_code}")
                        async for raw_line in resp.aiter_lines():
                            if raw_line is None:
                                continue
                            if raw_line == "":
                                continue
                            line = raw_line.strip()
                            # Accept both SSE (data: ...) and JSONL
                            if line.startswith("data: "):
                                line = line[len("data: "):].strip()
                                if line == "[DONE]":
                                    break
                            try:
                                chunk = json.loads(line)
                            except Exception:
                                # Not JSON, skip
                                continue
                            candidates = chunk.get("candidates", [])
                            if not candidates:
                                continue
                            parts = candidates[0].get("content", {}).get("parts", [])
                            for p in parts:
                                text = p.get("text")
                                if text:
                                    yield text
            return stream_gen()

        url = f"{base_url}:generateContent?key={self.api_key}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, json=payload)
            res.raise_for_status()
            data = res.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return ""
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts if "text" in p)
