from fastapi import HTTPException
from typing import Dict, Any
from app.llm.service.router_service import LatencyRouter
from app.core.logger import get_logger

logger = get_logger(__name__)

# Global defaults (can move to config later)
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 512
DEFAULT_STREAM = True


class LLMService:
    """Handles high-level LLM generation."""

    def __init__(self, router: LatencyRouter):
        self.router = router

    async def generate_response(self, params: Dict[str, Any]):
        try:
            # Apply defaults if missing
            params_dict = {
                "prompt": params.get("prompt", ""),
                "stream": params.get("stream", DEFAULT_STREAM),
                "model": params.get("model", "gpt-4o-mini"),
                "temperature": params.get("temperature", DEFAULT_TEMPERATURE),
                "max_tokens": params.get("max_tokens", DEFAULT_MAX_TOKENS),
            }

            # Let the LatencyRouter decide best model/provider
            result = await self.router.generate(params_dict)
            return {"text": result.get("text", "")}

        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))
