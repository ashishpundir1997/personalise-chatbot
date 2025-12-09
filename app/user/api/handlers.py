from typing import Any
from fastapi import HTTPException

from app.user.api.dto import DeleteAccountDTO
from app.user.service.user_service import UserService
import logging
import bcrypt


class UserHandler:
    def __init__(self, user_service: UserService, logger: logging.Logger):
        self.user_service = user_service
        self.logger = logger

    def _verify_password(self, password: str, hashed: str) -> bool:
        """Verify password against hashed password"""
        return bcrypt.checkpw(password.encode(), hashed.encode())

    async def delete_account(self, user_id: str, delete_data: DeleteAccountDTO) -> dict[str, Any]:
        """
        Delete user account and all related data (conversations, messages)
        """
        try:
            # Get user to verify password
            user = await self.user_service.get_user_by_id(user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            # Verify password for email auth users
            if user.user.auth_provider == "email":
                if not delete_data.password:
                    raise HTTPException(status_code=400, detail="Password is required for email authentication")
                
                # Verify password
                if not self._verify_password(delete_data.password, user.user.password_hash):
                    raise HTTPException(status_code=401, detail="Invalid password")

            # Delete user and all related data
            await self.user_service.delete_user_account(user_id)

            return {
                "status": True,
                "message": "Account deleted successfully",
                "data": None
            }

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting account: {e!s}")
            raise HTTPException(status_code=500, detail="Failed to delete account")

    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        """
        Get user profile information (name and email) for frontend display
        """
        try:
            user = await self.user_service.get_user_profile(user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            return {
                "status": True,
                "message": "User profile retrieved successfully",
                "data": {
                    "name": user.user.name,
                    "email": user.user.email
                }
            }

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting user profile: {e!s}")
            raise HTTPException(status_code=500, detail="Failed to get user profile")