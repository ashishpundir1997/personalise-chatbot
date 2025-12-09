from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.auth.api.dto import (
    GoogleAuthDTO,
    LoginDTO,
    PasswordResetDTO,
    PasswordResetRequestDTO,
    RefreshTokenDTO,
    UserRegisterDTO,
    EmailVerificationDTO,
    AuthSuccessResponse,
    BaseResponse,
)
from app.auth.api.dependencies import get_auth_handler
from app.auth.api.handlers import AuthHandler


class LogoutDTO(BaseModel):
    refresh_token: str


auth_router = APIRouter(prefix="/auth", tags=["Authentication"])


@auth_router.post("/register", response_model=BaseResponse)
async def register(user_data: UserRegisterDTO, auth_handler: AuthHandler = Depends(get_auth_handler)):
    """Step 1: Register a new user with email and password (sends OTP)"""
    return await auth_handler.register_user(user_data)


@auth_router.post("/verify-email", response_model=AuthSuccessResponse)
async def verify_email(
    verification_data: EmailVerificationDTO, auth_handler: AuthHandler = Depends(get_auth_handler)
):
    """Step 2: Verify email with OTP to complete email registration"""
    return await auth_handler.verify_email(verification_data)


@auth_router.post("/login", response_model=AuthSuccessResponse)
async def login(login_data: LoginDTO, auth_handler: AuthHandler = Depends(get_auth_handler)):
    """Login with email and password"""
    return await auth_handler.login(login_data)


@auth_router.post("/google", response_model=AuthSuccessResponse)
async def google_auth(
    google_data: GoogleAuthDTO, auth_handler: AuthHandler = Depends(get_auth_handler)
):
    """Authenticate with Google"""
    return await auth_handler.google_auth(google_data)


@auth_router.post("/password-reset-request", response_model=BaseResponse)
async def request_password_reset(
    reset_data: PasswordResetRequestDTO, auth_handler: AuthHandler = Depends(get_auth_handler)
):
    """Step 1: Request password reset (sends OTP to email)"""
    return await auth_handler.request_password_reset(reset_data)


@auth_router.post("/password-reset", response_model=BaseResponse)
async def reset_password(reset_data: PasswordResetDTO, auth_handler: AuthHandler = Depends(get_auth_handler)):
    """Step 2: Reset password with OTP and new password"""
    return await auth_handler.reset_password(reset_data)


@auth_router.post("/refresh", response_model=AuthSuccessResponse)
async def refresh_token(
    refresh_token_dto: RefreshTokenDTO, auth_handler: AuthHandler = Depends(get_auth_handler)
):
    """Refresh access token using refresh token"""
    try:
        return await auth_handler.refresh_token(refresh_token_dto.refresh_token)
    except ValueError as e:
        if str(e) == "Token has expired":
            raise HTTPException(status_code=401, detail="Refresh token has expired")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        auth_handler.logger.error(f"Error refreshing token: {e!s}")
        raise HTTPException(status_code=500, detail="Internal server error")


@auth_router.post("/logout", response_model=BaseResponse)
async def logout(
    logout_dto: LogoutDTO,
    auth_handler: AuthHandler = Depends(get_auth_handler)
):
    """Logout user by blacklisting refresh token and updating logout timestamp"""
    return await auth_handler.logout(logout_dto.refresh_token)