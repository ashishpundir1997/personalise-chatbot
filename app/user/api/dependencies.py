from typing import Annotated

from fastapi import Depends, Request

from app.user.api.handlers import UserHandler


def get_user_handler(request: Request) -> UserHandler:
    """Get user handler from app state."""
    if not hasattr(request.app.state, "user_service"):
        raise RuntimeError("User service not initialized. Ensure main.py startup wires app.state.*")
    
    if hasattr(request.app.state, "user_handler"):
        return request.app.state.user_handler
    
    logger = getattr(request.app.state, "logger", None)
    user_handler = UserHandler(request.app.state.user_service, logger)
    request.app.state.user_handler = user_handler
    return user_handler


# Type aliases for cleaner dependency injection
UserHandlerDep = Annotated[UserHandler, Depends(get_user_handler)]
