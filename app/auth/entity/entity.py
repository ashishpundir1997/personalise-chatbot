from pydantic import BaseModel
from typing import Optional


class GoogleUser(BaseModel):
    id: str
    name: str
    email: str
    image: str | None = None


class GoogleAccount(BaseModel):
    provider: str
    type: str
    providerAccountId: str
    access_token: str
    expires_at: int
    refresh_token: str
    scope: str
    token_type: str
    id_token: str


class GoogleProfile(BaseModel):
    iss: str
    azp: Optional[str] = None
    aud: str
    sub: str
    hd: Optional[str] = None
    email: str
    email_verified: bool
    at_hash: str
    name: Optional[str] = None  # Made optional as it may not always be present
    given_name: Optional[str] = None
    picture: Optional[str] = None
    family_name: Optional[str] = None
    iat: int
    exp: int


class GoogleAuthData(BaseModel):
    user: GoogleUser
    account: GoogleAccount
    profile: GoogleProfile




