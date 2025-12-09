# app/llm/api/router.py

from fastapi import APIRouter, Depends
from ..api.handler import LLMHandler
from ..service.llm_service import LLMService
from ..service.router_service import LatencyRouter
from app.auth.api.dto import BaseResponse

# Dependency injection setup
def get_llm_handler() -> LLMHandler:
    router = LatencyRouter()
    llm_service = LLMService(router)
    return LLMHandler(llm_service)


# Main LLM router
llm_router = APIRouter(prefix="/llm", tags=["LLM"])


@llm_router.get("/health", response_model=BaseResponse)
async def health(handler: LLMHandler = Depends(get_llm_handler)):
    """Health check for active providers."""
    health_data = await handler.health()
    return BaseResponse(
        status=True,
        message="Health check successful",
        data=health_data
    )


@llm_router.get("/providers", response_model=BaseResponse)
async def get_providers(handler: LLMHandler = Depends(get_llm_handler)):
    """Return list of active and available providers."""
    providers_data = await handler.providers()
    return BaseResponse(
        status=True,
        message="Providers fetched successfully",
        data=providers_data.model_dump() if hasattr(providers_data, 'model_dump') else providers_data
    )

