from pydantic import BaseModel, constr, Field, ConfigDict, AliasChoices
from typing import Optional
import re

class UserRegisterDTO(BaseModel):
    """DTO for user registration"""

    name: str
    email: str
    password: constr(min_length=8, max_length=100)  # type: ignore


class EmailVerificationDTO(BaseModel):
    """DTO for email verification"""

    email: str
    otp: str  # type: ignore


class LoginDTO(BaseModel):
    """DTO for user login"""

    email: str
    password: str


class GoogleUserDTO(BaseModel):
    """DTO for Google user data - optional as we extract from ID token"""

    id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    image: str | None = None


class GoogleAccountDTO(BaseModel):
    """DTO for Google account data"""
    model_config = ConfigDict(populate_by_name=True)

    provider: Optional[str] = "google"
    type: Optional[str] = "oauth"
    providerAccountId: Optional[str] = Field(default=None, validation_alias=AliasChoices("providerAccountId", "provider_account_id"))
    access_token: Optional[str] = None
    expires_at: Optional[int] = None
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
    token_type: Optional[str] = "Bearer"
    id_token: str  # Required - this is the main token we verify


class GoogleProfileDTO(BaseModel):
    """DTO for Google profile data - most fields optional as we extract from ID token"""
    model_config = ConfigDict(populate_by_name=True)

    iss: Optional[str] = None
    azp: Optional[str] = None
    aud: Optional[str] = None
    sub: Optional[str] = None
    hd: Optional[str] = None
    email: Optional[str] = None
    email_verified: Optional[bool] = None
    at_hash: Optional[str] = None
    name: Optional[str] = None
    given_name: Optional[str] = None
    picture: Optional[str] = None
    family_name: Optional[str] = None
    iat: Optional[int] = None
    exp: Optional[int] = None


class GoogleAuthDTO(BaseModel):
    """DTO for Google authentication - only account.id_token is required, rest is optional"""

    account: GoogleAccountDTO  # Required - contains id_token
    user: Optional[GoogleUserDTO] = None  # Optional - we extract from ID token
    profile: Optional[GoogleProfileDTO] = None  # Optional - we extract from ID token

    

class AppleAuthDTO(BaseModel):
    """DTO for Apple authentication"""

    identity_token: str



class PasswordResetRequestDTO(BaseModel):
    """DTO for password reset request"""

    email: str


class PasswordResetDTO(BaseModel):
    """DTO for password reset"""
    email: str
    otp: str
    new_password: constr(min_length=8, max_length=100) # type: ignore
    # type: ignore


class RefreshTokenDTO(BaseModel):
    refresh_token: str


class BaseResponse(BaseModel):
    status: bool
    message: str
    data: dict | None = None


class TokenData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class AuthSuccessResponse(BaseModel):
    status: bool
    message: str
    data: TokenData
