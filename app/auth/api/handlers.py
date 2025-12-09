from typing import Any
from fastapi import HTTPException

from app.auth.api.dto import (
    GoogleAuthDTO,
    LoginDTO,
    PasswordResetDTO,
    PasswordResetRequestDTO,
    UserRegisterDTO,
    EmailVerificationDTO,
)
from app.auth.service.auth_service import AuthService
from app.auth.entity.entity import GoogleAuthData, GoogleUser, GoogleAccount, GoogleProfile
import logging


def model_google_auth_dto_to_entity(dto: GoogleAuthDTO) -> GoogleAuthData:
    """Convert GoogleAuthDTO to GoogleAuthData entity - handles optional fields"""
    return GoogleAuthData(
        user=GoogleUser(
            id=dto.user.id or "",
            name=dto.user.name or "",
            email=dto.user.email or "",
            image=dto.user.image
        ) if dto.user else GoogleUser(id="", name="", email="", image=None),
        account=GoogleAccount(
            provider=dto.account.provider or "google",
            type=dto.account.type or "oauth",
            providerAccountId=dto.account.providerAccountId or "",
            access_token=dto.account.access_token or "",
            expires_at=dto.account.expires_at or 0,
            refresh_token=dto.account.refresh_token or "",
            scope=dto.account.scope or "",
            token_type=dto.account.token_type or "Bearer",
            id_token=dto.account.id_token
        ),
        profile=GoogleProfile(
            iss=dto.profile.iss or "",
            azp=dto.profile.azp,
            aud=dto.profile.aud or "",
            sub=dto.profile.sub or "",
            hd=dto.profile.hd,
            email=dto.profile.email or "",
            email_verified=dto.profile.email_verified or False,
            at_hash=dto.profile.at_hash or "",
            name=dto.profile.name,
            given_name=dto.profile.given_name,
            picture=dto.profile.picture,
            family_name=dto.profile.family_name,
            iat=dto.profile.iat or 0,
            exp=dto.profile.exp or 0
        ) if dto.profile else GoogleProfile(
            iss="", aud="", sub="", email="", email_verified=False, at_hash="", iat=0, exp=0
        )
    )


class AuthHandler:
    def __init__(self, auth_service: AuthService, logger: logging.Logger):
        self.auth_service = auth_service
        self.logger = logger

    async def register_user(self, user_data: UserRegisterDTO) -> dict[str, Any]:
        try:
            result = await self.auth_service.register_with_email(
                user_data.email,
                user_data.password,
                user_data.name,
            )
            # Check if OTP verification is required
            if result.get("requires_verification"):
                return {
                    "status": True,
                    "message": result["message"],
                    "data": {
                        "requires_verification": True,
                        "email": result["email"]
                    }
                }
            # If somehow tokens are returned (shouldn't happen), return them
            return {
                "status": True,
                "message": result.get("message", "Registration successful"),
                "data": result
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error during registration: {e!s}")
            raise HTTPException(status_code=500, detail=str(e) if str(e) else "Registration failed")
    
    async def verify_email(self, verification_data: EmailVerificationDTO) -> dict[str, Any]:
        try:
            tokens = await self.auth_service.verify_email(
                verification_data.email,
                verification_data.otp,
            )
            return {
                "status": True,
                "message": "Email verified successfully",
                "data": {
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens["refresh_token"],
                    "token_type": "bearer",
                    "expires_in": 86400  # 24 Hr in seconds
                }
            }
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error during email verification: {e!s}")
            raise HTTPException(status_code=500, detail="Email verification failed")

    async def login(self, login_data: LoginDTO) -> dict[str, Any]:
        try:
            tokens = await self.auth_service.login_with_email(
                login_data.email, login_data.password
            )
            return {
                "status": True,
                "message": "Login successful",
                "data": {
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens["refresh_token"],
                    "token_type": "bearer",
                    "expires_in": 86400  # 24 Hr in seconds
                }
            }
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            self.logger.error(f"Error during login: {e!s}")
            raise HTTPException(status_code=500, detail=str(e) if str(e) else "Login failed")

    async def google_auth(self, google_auth_request: GoogleAuthDTO) -> dict[str, Any]:
        try:
            google_auth_entity = model_google_auth_dto_to_entity(google_auth_request)
            tokens = await self.auth_service.register_with_google(google_auth_entity)
            return {
                "status": True,
                "message": "Login successful",
                "data": {
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens["refresh_token"],
                    "token_type": "bearer",
                    "expires_in": 86400  # 24Hr in seconds
                }
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error during Google authentication: {e!s}")
            raise HTTPException(status_code=500, detail="Google authentication failed")



    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        try:
            tokens = await self.auth_service.refresh_token(refresh_token)
            return {
                "status": True,
                "message": "Token refreshed successfully",
                "data": {
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens["refresh_token"],
                    "token_type": "bearer",
                    "expires_in": 86400  # 24 Hr in seconds
                }
            }
        except ValueError as e:
            if str(e) == "Token has expired":
                raise HTTPException(status_code=401, detail="Refresh token has expired")
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            self.logger.error(f"Error refreshing token: {e!s}")
            raise HTTPException(status_code=500, detail="Token refresh failed")

    async def logout(self, refresh_token: str) -> dict[str, Any]:
        """Logout user by blacklisting refresh token and updating logout timestamp"""
        try:
            await self.auth_service.logout(refresh_token)
            return {
                "status": True,
                "message": "Logged out successfully",
                "data": {}
            }
        except Exception as e:
            self.logger.error(f"Error during logout: {e!s}")
            # Logout should generally succeed even if there's an error
            return {
                "status": True,
                "message": "Logged out successfully",
                "data": {}
            }

    async def request_password_reset(self, reset_data: PasswordResetRequestDTO) -> dict[str, Any]:
        try:
            await self.auth_service.request_password_reset(reset_data.email)
            return {
                "status": True,
                "message": "Password reset instructions sent to email",
                "data": {
                    "email": reset_data.email
                }
            }
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error requesting password reset: {e!s}")
            raise HTTPException(status_code=500, detail="Failed to send reset instructions")

    async def reset_password(self, reset_data: PasswordResetDTO) -> dict[str, Any]:
        try:
            await self.auth_service.reset_password(
                reset_data.email, 
                reset_data.otp, 
                reset_data.new_password
                
            )
            
            return {
                "status": True,
                "message": "Password reset successful",
                "data": {
                    "email": reset_data.email
                }
            }
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            self.logger.error(f"Error resetting password: {e!s}")
            raise HTTPException(status_code=500, detail="Password reset failed")