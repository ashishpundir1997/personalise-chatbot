import random
import string
import json
from datetime import datetime, timedelta
import os
import bcrypt
from fastapi import HTTPException
from app.user.service.user_service import UserService
from app.user.entities.aggregate import UserAggregate
import logging
from pkg.redis.client import RedisClient
from pkg.smtp_client.client import EmailClient
from pkg.auth_token_client.client import TokenClient, TokenPayload  # For JWT
import jwt
import httpx
from app.auth.entity.entity import GoogleAuthData
from app.agents.zep_user_service import ZepUserService
from typing import Any

# Redis keys for OTP storage
REDIS_PASSWORD_RESET_OTP = "password_reset_otp_"
REDIS_EMAIL_REGISTRATION_OTP = "email_registration_otp_"
REDIS_EMAIL_REGISTRATION_DATA = "email_registration_data_"
REDIS_BLACKLISTED_TOKEN = "blacklisted_token_"
REDIS_LAST_LOGOUT_AT = "last_logout_at_"

class AuthService:
    def __init__(
        self,
        user_service: UserService,
        token_client: TokenClient,
        redis_client: RedisClient,
        logger: logging.Logger,
        smtp_client: EmailClient,
        zep_user_service: ZepUserService | None = None,
    ):
        self.user_service = user_service
        self.token_client = token_client
        self.redis_client = redis_client
        self.logger = logger
        self.smtp_client = smtp_client
        self.google_client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
        # Initialize Zep user service if not provided
        self.zep_user_service = zep_user_service or ZepUserService(logger)

    def _hash_password(self, password: str) -> str:
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode(), salt).decode()

    def _verify_password(self, password: str, hashed: str) -> bool:
        return bcrypt.checkpw(password.encode(), hashed.encode())

    def _create_tokens(self, user_id: str, email: str, role: str = "MEMBER") -> dict[str, str]:
        payload = TokenPayload(
            user_id=user_id,
            role=role,
            email=email
        )
        return self.token_client.create_tokens(payload)

    async def register_with_email(self, email: str, password: str, name: str) -> dict[str, str]:
        """Register a new user - sends OTP for email verification"""
        try:
            # Check if user already exists in database (verified user)
            existing_user = await self.user_service.get_user_by_email(email)
            if existing_user:
                raise HTTPException(status_code=400, detail="Email already registered. Please login.")

            pending_registration_data = self.redis_client.get_value(REDIS_EMAIL_REGISTRATION_DATA + email)
            if pending_registration_data:
                self.redis_client.delete(REDIS_EMAIL_REGISTRATION_OTP + email)
                self.redis_client.delete(REDIS_EMAIL_REGISTRATION_DATA + email)

            otp = "".join(random.choices(string.digits, k=6))
            self.redis_client.set_value(REDIS_EMAIL_REGISTRATION_OTP + email, otp, expiry=600)
            
            hashed_password = self._hash_password(password)
            registration_data = {
                "email": email,
                "password_hash": hashed_password,
                "name": name,
                "auth_provider": "email"
            }
            self.redis_client.set_value(
                REDIS_EMAIL_REGISTRATION_DATA + email,
                json.dumps(registration_data),
                expiry=600
            )
            
            html_content = f"""
            <html>
            <body style='font-family: Arial, sans-serif; background-color: #f9f9f9; padding: 24px;'>
                <div style='max-width: 480px; margin: auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px #eee; padding: 32px;'>
                    <h2 style='color: #2a2a2a;'>Welcome to Neo!</h2>
                    <p>Dear {name},</p>
                    <p>Thank you for registering with Neo. To verify your account, please use the code below:</p>
                    <div style='font-size: 2em; font-weight: bold; letter-spacing: 4px; color: #007bff; margin: 24px 0;'>{otp}</div>
                    <p>This code is valid for 10 minutes.</p>
                    <p>If you did not request this, please ignore this email.</p>
                    <hr style='margin: 32px 0;'>
                    <p style='font-size: 0.9em; color: #888;'>Neo Security Team</p>
                </div>
            </body>
            </html>
            """
            body = f"Your Neo verification code is: {otp}\nThis code is valid for 10 minutes."
            await self.smtp_client.send_email(
                to_addresses=[email],
                subject="Neo Account Verification Code",
                body=body,
                html_content=html_content
            )
            
            return {
                "message": "OTP sent to email. Please verify your email to complete registration.",
                "requires_verification": True,
                "email": email
            }
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error during registration: {e!s}")
            raise HTTPException(status_code=500, detail="Registration failed")

    async def verify_email(self, email: str, otp: str) -> dict[str, str]:
        """Verify OTP and complete email registration"""
        try:
            otp_key = REDIS_EMAIL_REGISTRATION_OTP + email
            stored_otp = self.redis_client.get_value(otp_key)
            
            if not stored_otp or str(stored_otp).strip() != str(otp).strip():
                raise HTTPException(status_code=400, detail="Invalid or expired OTP")
            
            registration_data = self.redis_client.get_value(REDIS_EMAIL_REGISTRATION_DATA + email)
            if not registration_data:
                raise HTTPException(status_code=400, detail="Registration data expired. Please register again.")
            
            if isinstance(registration_data, str):
                registration_data = json.loads(registration_data)
            
            existing_user = await self.user_service.get_user_by_email(email)
            if existing_user:
                self.redis_client.delete(REDIS_EMAIL_REGISTRATION_OTP + email)
                self.redis_client.delete(REDIS_EMAIL_REGISTRATION_DATA + email)
                raise HTTPException(status_code=400, detail="Email already registered. Please login.")
            
            user_aggregate = await self.user_service.create_user(
                email=registration_data["email"],
                password_hash=registration_data["password_hash"],
                name=registration_data["name"],
                is_email_verified=True,
                auth_provider=registration_data["auth_provider"]
            )
            
            if not user_aggregate or not user_aggregate.user:
                raise HTTPException(status_code=500, detail="Failed to create user")
            
            # Create user in Zep
            try:
                await self.zep_user_service.ensure_user_exists(
                    user_id=user_aggregate.user.id,
                    email=user_aggregate.user.email,
                    name=user_aggregate.user.name,
                    metadata={"auth_provider": registration_data["auth_provider"]}
                )
            except Exception as e:
                self.logger.warning(f"Failed to create user in Zep during email verification: {e}")
                # Continue even if Zep fails
            
            self.redis_client.delete(REDIS_EMAIL_REGISTRATION_OTP + email)
            self.redis_client.delete(REDIS_EMAIL_REGISTRATION_DATA + email)
            
            tokens = self._create_tokens(
                user_id=user_aggregate.user.id,
                email=email
            )
            
            return tokens

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error verifying email: {e!s}")
            raise HTTPException(status_code=500, detail="Email verification failed")

    async def login_with_email(self, email: str, password: str) -> dict[str, str]:
        try:
            user_aggregate = await self.user_service.get_user_by_email(email)
            if not user_aggregate or not user_aggregate.user:
                raise HTTPException(status_code=401, detail="The email is not registered. Please register first.")

            if not self._verify_password(password, user_aggregate.user.password_hash):
                raise HTTPException(status_code=401, detail="The password is incorrect. Please try again.")
            
            if not user_aggregate.user.is_email_verified:
                raise HTTPException(status_code=403, detail="Email not verified. Please verify your email to login.")

            # Ensure user exists in Zep (in case it was created before Zep integration)
            try:
                await self.zep_user_service.ensure_user_exists(
                    user_id=user_aggregate.user.id,
                    email=user_aggregate.user.email,
                    name=user_aggregate.user.name,
                    metadata={"auth_provider": user_aggregate.user.auth_provider}
                )
            except Exception as e:
                self.logger.warning(f"Failed to ensure user exists in Zep during login: {e}")
                # Continue even if Zep fails

            tokens = self._create_tokens(user_id=user_aggregate.user.id, email=email)

            return {
                "message": "Login successful",
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "token_type": "bearer",
            }
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error during login: {e!s}")
            raise HTTPException(status_code=500, detail="Login failed")

    async def request_password_reset(self, email: str) -> None:
        user_aggregate = await self.user_service.get_user_by_email(email)
        if not user_aggregate or not user_aggregate.user:
            raise HTTPException(status_code=404, detail="Email not registered")

        if user_aggregate.user.auth_provider != "email":
            raise HTTPException(
                status_code=400,
                detail=f"This account uses {user_aggregate.user.auth_provider}. Please log in using it."
            )

        otp = "".join(random.choices(string.digits, k=6))
        self.redis_client.set_value(REDIS_PASSWORD_RESET_OTP + email, otp, expiry=600)  

        html_content = f"""
        <html>
        <body style='font-family: Arial, sans-serif; background-color: #f9f9f9; padding: 24px;'>
            <div style='max-width: 480px; margin: auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px #eee; padding: 32px;'>
                <h2 style='color: #2a2a2a;'>Neo Password Reset</h2>
                <p>Dear User,</p>
                <p>We received a request to reset your password. Please use the code below to proceed:</p>
                <div style='font-size: 2em; font-weight: bold; letter-spacing: 4px; color: #e67e22; margin: 24px 0;'>{otp}</div>
                <p>This code is valid for 10 minutes.</p>
                <p>If you did not request a password reset, please ignore this email or contact support.</p>
                <hr style='margin: 32px 0;'>
                <p style='font-size: 0.9em; color: #888;'>Neo Security Team</p>
            </div>
        </body>
        </html>
        """
        body = f"Your Neo password reset code is: {otp}\nThis code is valid for 10 minutes."
        await self.smtp_client.send_email(
            to_addresses=[email],
            subject="Neo Password Reset Code",
            body=body,
            html_content=html_content
        )

    async def reset_password(self, email: str, otp: str, new_password: str) -> None:
        user_aggregate = await self.user_service.get_user_by_email(email)
        if not user_aggregate or not user_aggregate.user:
            raise HTTPException(status_code=404, detail="User not found")

        if user_aggregate.user.auth_provider != "email":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot reset password for {user_aggregate.user.auth_provider} account"
            )

        stored_otp = self.redis_client.get_value(REDIS_PASSWORD_RESET_OTP + email)
        if not stored_otp or str(stored_otp).strip() != str(otp).strip():
            raise HTTPException(status_code=400, detail="Invalid OTP")

        hashed_password = self._hash_password(new_password)
        await self.user_service.update_user_password(user_aggregate.user.id, hashed_password)

        self.redis_client.delete(REDIS_PASSWORD_RESET_OTP + email)

    async def refresh_token(self, refresh_token: str) -> dict[str, str]:
        try:
            payload = self.token_client.decode_token(refresh_token, is_refresh=True)
            
            if self.redis_client.get_value(REDIS_BLACKLISTED_TOKEN + refresh_token):
                raise HTTPException(status_code=401, detail="Refresh token has been revoked")
            
            user_aggregate = await self.user_service.get_user_by_id(payload["user_id"])
            if not user_aggregate or not user_aggregate.user:
                raise HTTPException(status_code=401, detail="User not found")
            
            tokens = self._create_tokens(
                user_id=user_aggregate.user.id,
                email=user_aggregate.user.email,
                role=payload.get("role", "MEMBER")
            )

            try:
                exp = payload.get("exp")
                if exp:
                    remaining_seconds = max(0, exp - int(datetime.utcnow().timestamp()))
                    if remaining_seconds > 0:
                        self.redis_client.set_value(
                            REDIS_BLACKLISTED_TOKEN + refresh_token,
                            "true",
                            expiry=remaining_seconds,
                        )
            except Exception:
                pass
            
            return tokens
            
        except ValueError as e:
            error_msg = str(e)
            if "expired" in error_msg.lower():
                raise HTTPException(status_code=401, detail="Refresh token has expired")
            raise HTTPException(status_code=400, detail=error_msg)
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error refreshing token: {e!s}")
            raise HTTPException(status_code=500, detail="Token refresh failed")

    async def verify_token(self, token: str) -> dict:
        try:
            if self.redis_client.get_value(REDIS_BLACKLISTED_TOKEN + token):
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            
            # Decode token first - if this fails, return 401 immediately
            try:
                payload = self.token_client.decode_token(token, is_refresh=False)
            except (ValueError, Exception) as e:
                # Any error in token decoding means invalid/expired token
                error_msg = str(e).lower()
                if "expired" in error_msg:
                    raise HTTPException(status_code=401, detail="Invalid or expired token")
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            
            user_id = payload.get("user_id")
            
            if not user_id:
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            
            # Check if token was issued before logout timestamp (instant logout)
            last_logout_at = self.redis_client.get_value(REDIS_LAST_LOGOUT_AT + user_id)
            if last_logout_at:
                try:
                    token_iat = payload.get("iat")
                    if token_iat is not None:
                        logout_ts = int(last_logout_at) if isinstance(last_logout_at, str) else last_logout_at
                        token_iat_int = int(token_iat) if isinstance(token_iat, (int, float, str)) else None
                        if token_iat_int and logout_ts > token_iat_int:
                            raise HTTPException(status_code=401, detail="Invalid or expired token")
                except (ValueError, TypeError):
                    pass  # If comparison fails, continue with normal validation
            
            # Verify user exists
            try:
                user_aggregate = await self.user_service.get_user_by_id(user_id)
            except Exception as e:
                # If database query fails, treat as invalid token (don't expose DB errors)
                self.logger.error(f"Error fetching user during token verification: {e!s}")
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            
            if not user_aggregate or not user_aggregate.user:
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            
            return payload
        except HTTPException:
            raise
        except Exception as e:
            # Catch any other unexpected errors and return 401
            self.logger.error(f"Error verifying token: {e!s}")
            raise HTTPException(status_code=401, detail="Invalid or expired token")


    # LOGOUT METHOD 
    async def logout(self, refresh_token: str) -> None:
        """Logout user by blacklisting refresh token and storing logout timestamp"""
        try:
            # Decode refresh token to get user_id and expiry
            refresh_payload = self.token_client.decode_token(refresh_token, is_refresh=True)
            user_id = refresh_payload.get("user_id")
            
            if not user_id:
                self.logger.warning("No user_id found in refresh token during logout")
                return
            
            # Store logout timestamp → invalidates all access tokens issued before this moment
            current_timestamp = int(datetime.utcnow().timestamp())
            # Store for 30 days (longer than max token expiry)
            self.redis_client.set_value(
                REDIS_LAST_LOGOUT_AT + user_id,
                str(current_timestamp),
                expiry=30 * 24 * 60 * 60  # 30 days
            )
            
            # Blacklist refresh token
            exp = refresh_payload.get("exp")
            if exp:
                remaining_seconds = max(0, exp - int(datetime.utcnow().timestamp()))
                if remaining_seconds > 0:
                    self.redis_client.set_value(
                        REDIS_BLACKLISTED_TOKEN + refresh_token,
                        "true",
                        expiry=remaining_seconds
                    )
        except (ValueError, HTTPException) as e:
            self.logger.warning(f"Invalid refresh token during logout: {e!s}")
            # Don't throw - logout should be idempotent
        except Exception as e:
            self.logger.error(f"Error during logout: {e!s}")
            # Logout should not throw exception

    async def _verify_google_id_token(self, id_token: str) -> dict[str, Any]:
        try:
            if not id_token or not isinstance(id_token, str) or not id_token.strip():
                raise ValueError("ID token is missing or invalid")
            
            token_parts = id_token.split('.')
            if len(token_parts) != 3:
                raise ValueError(f"Invalid ID token format: expected 3 segments, got {len(token_parts)}")
            
            unverified = jwt.decode(id_token, options={"verify_signature": False})
            
            exp = unverified.get("exp")
            if exp and int(exp) < int(datetime.utcnow().timestamp()):
                raise ValueError("ID token has expired")
            
            iss = unverified.get("iss")
            if iss not in ["accounts.google.com", "https://accounts.google.com"]:
                raise ValueError(f"Invalid issuer: {iss}")
            
            if self.google_client_id:
                aud = unverified.get("aud")
                if aud != self.google_client_id:
                    raise ValueError(f"Invalid audience: expected {self.google_client_id}, got {aud}")
            
            if not unverified.get("sub"):
                raise ValueError("Missing 'sub' claim in ID token")
            
            if not unverified.get("email"):
                raise ValueError("Missing 'email' claim in ID token")
            
            return unverified
            
        except jwt.ExpiredSignatureError:
            raise ValueError("ID token has expired")
        except jwt.InvalidTokenError as e:
            raise ValueError(f"Invalid ID token: {str(e)}")
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"Error verifying Google ID token: {e!s}")
            raise ValueError(f"Failed to verify ID token: {str(e)}")

    async def register_with_google(
        self, google_auth_data: GoogleAuthData
    ) -> dict[str, str]:
        try:
            if not google_auth_data.account.id_token:
                raise ValueError("ID token is required for Google authentication")
            
            id_info = await self._verify_google_id_token(google_auth_data.account.id_token)
            
            email = id_info.get("email")
            if not email:
                raise ValueError("Email not found in verified ID token")
            
            profile_name = google_auth_data.profile.name if google_auth_data.profile else None
            user_name = google_auth_data.user.name if google_auth_data.user else None
            profile_given = google_auth_data.profile.given_name if google_auth_data.profile else None
            profile_family = google_auth_data.profile.family_name if google_auth_data.profile else None
            
            name = (
                id_info.get("name") 
                or profile_name
                or user_name
                or (f"{id_info.get('given_name', '')} {id_info.get('family_name', '')}".strip() or None)
                or (f"{profile_given or ''} {profile_family or ''}".strip() or None)
                or email.split("@")[0]
            )
            
            google_id = id_info.get("sub")
            if not google_id:
                raise ValueError("Google ID (sub) not found in verified ID token")
            
            existing_user = await self.user_service.get_user_by_email(email)

            if existing_user and existing_user.user:
                if existing_user.user.auth_provider != "google":
                    raise HTTPException(
                        status_code=400,
                        detail="Email already registered with different provider",
                    )

                # Ensure user exists in Zep (in case it was created before Zep integration)
                try:
                    await self.zep_user_service.ensure_user_exists(
                        user_id=existing_user.user.id,
                        email=existing_user.user.email,
                        name=existing_user.user.name,
                        metadata={"auth_provider": "google"}
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to ensure user exists in Zep during Google login: {e}")

                tokens = self._create_tokens(
                    user_id=existing_user.user.id,
                    email=email
                )
                return tokens

            user_aggregate = await self.user_service.create_user(
                email=email,
                password_hash="",
                auth_provider="google",
                name=name,
                is_email_verified=True,
                auth_provider_detail=google_auth_data.model_dump(),
                google_id=google_id,
                image_url=(
                    (google_auth_data.user.image if google_auth_data.user else None)
                    or (google_auth_data.profile.picture if google_auth_data.profile else None)
                    or id_info.get("picture")
                ),
            )
            
            if not user_aggregate or not user_aggregate.user:
                raise HTTPException(status_code=500, detail="Failed to create user")

            # Create user in Zep
            try:
                await self.zep_user_service.ensure_user_exists(
                    user_id=user_aggregate.user.id,
                    email=user_aggregate.user.email,
                    name=user_aggregate.user.name,
                    metadata={"auth_provider": "google"}
                )
            except Exception as e:
                self.logger.warning(f"Failed to create user in Zep during Google registration: {e}")
                # Continue even if Zep fails

            tokens = self._create_tokens(
                user_id=user_aggregate.user.id,
                email=email
            )

            return tokens

        except ValueError as e:
            self.logger.error(f"Google token verification failed: {e!s}")
            raise HTTPException(status_code=400, detail=f"Invalid token: {e!s}")
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Google authentication error: {e!s}")
            raise HTTPException(status_code=500, detail="Authentication failed")
