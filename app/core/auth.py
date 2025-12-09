from fastapi import Request, HTTPException, status
from fastapi.security.api_key import APIKeyHeader
from app.core.config import settings

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)


async def require_api_key(request: Request, api_key: str = None):
    """Middleware to validate API key header."""
    key = api_key or request.headers.get("x-api-key")

    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key missing",
        )

    valid_keys = {
        settings.OPENAI_API_KEY,
        settings.ANTHROPIC_API_KEY,
        settings.GEMINI_API_KEY,
    }

    if key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )
