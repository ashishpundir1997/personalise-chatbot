from fastapi import APIRouter, Depends, HTTPException
from app.user.api.dto import DeleteAccountDTO
from app.user.api.dependencies import get_user_handler
from app.user.api.handlers import UserHandler
from app.auth.api.dependencies import get_current_user

user_router = APIRouter(prefix="/user", tags=["User"])


@user_router.get("/profile")
async def get_profile(
    current_user: dict = Depends(get_current_user),
    user_handler: UserHandler = Depends(get_user_handler)
):
    """
    Get user profile information (name and email) for frontend display.
    Requires authentication.
    """
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found in token")
    
    return await user_handler.get_user_profile(user_id)


@user_router.delete("/account")
async def delete_account(
    delete_data: DeleteAccountDTO,
    current_user: dict = Depends(get_current_user),
    user_handler: UserHandler = Depends(get_user_handler)
):
    """
    Delete user account and all related data (conversations and messages).
    Requires authentication and password confirmation for email auth users.
    """
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found in token")
    
    return await user_handler.delete_account(user_id, delete_data)