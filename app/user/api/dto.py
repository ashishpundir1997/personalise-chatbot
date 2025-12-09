from pydantic import BaseModel, Field


class DeleteAccountDTO(BaseModel):
    """Request DTO for deleting user account"""
    password: str = Field(..., description="User's password for confirmation")


class DeleteAccountResponseDTO(BaseModel):
    """Response DTO for delete account"""
    status: bool
    message: str


class UserProfileResponseDTO(BaseModel):
    """Response DTO for user profile"""
    name: str = Field(..., description="User's name")
    email: str = Field(..., description="User's email address")