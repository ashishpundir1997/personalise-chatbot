from typing import Annotated

from fastapi import Depends, Request, HTTPException

from app.user.api.handlers import UserHandler


def get_user_handler(request: Request) -> UserHandler:
    """Get user handler from app state."""
    # Check if startup completed successfully
    if not getattr(request.app.state, "startup_complete", False):
        raise HTTPException(
            status_code=503,
            detail="Service is starting up. Please retry in a moment."
        )
    
    # Check for startup errors
    startup_error = getattr(request.app.state, "startup_error", None)
    if startup_error:
        raise HTTPException(
            status_code=503,
            detail=f"Service initialization failed: {startup_error}"
        )
    
    if not hasattr(request.app.state, "user_service"):
        raise HTTPException(
            status_code=503,
            detail="User service not initialized. Check application logs."
        )
    
    if hasattr(request.app.state, "user_handler"):
        return request.app.state.user_handler
    
    logger = getattr(request.app.state, "logger", None)
    user_handler = UserHandler(request.app.state.user_service, logger)
    request.app.state.user_handler = user_handler
    return user_handler


# Type aliases for cleaner dependency injection
UserHandlerDep = Annotated[UserHandler, Depends(get_user_handler)]
