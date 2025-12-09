from typing import Any
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
from app.user.entities.aggregate import UserAggregate
from app.user.entities.entity import User as UserEntity
from app.user.repository.sql_schema.user import UserModel
from app.user.service.user_service import IUserRepository
from app.chat.repository.sql_schema.conversation import ConversationModel, MessageModel
import logging


class UserRepository(IUserRepository):
    def __init__(self,  db_session_factory , logger: logging.Logger):
        self.db_session_factory = db_session_factory
        self.logger = logger

    async def create_user(
        self,
        email: str,
        password_hash: str,
        is_email_verified: bool,
        name: str,
        auth_provider: str = "email",
        auth_provider_detail: dict = None,
        profile_colour: str = "",
        google_id: str | None = None,
        image_url: str | None = None
    ) -> UserAggregate:
        """Create a new user"""
        if auth_provider_detail is None:
            auth_provider_detail = {}
        try:
            async with self.db_session_factory() as session:
                async with session.begin():
                    user = UserModel(
                        email=email,
                        password_hash=password_hash,
                        auth_provider=auth_provider,
                        auth_provider_detail=auth_provider_detail,
                        name=name,
                        phone="",
                        image_url="",
                        is_email_verified=is_email_verified,
                        profile_colour=profile_colour,
                    )
                    session.add(user)

                await session.refresh(user)

                user_entity = UserEntity(
                    id=user.user_id,
                    email=user.email,
                    password_hash=user.password_hash,
                    auth_provider=user.auth_provider,
                    is_email_verified=user.is_email_verified,
                    name=user.name or "",
                    phone=user.phone or "",
                    image_url=user.image_url or "",
                    is_profile_created=user.is_profile_created,
                    profile_colour=user.profile_colour or "",
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                )

                return UserAggregate(user=user_entity, events=["UserCreated"])

        except Exception as e:
            self.logger.error(f"Error creating user: {e!s}")
            raise HTTPException(status_code=500, detail="Failed to create user")

    async def get_user_by_email(self, email: str) -> UserAggregate | None:
        try:
            async with self.db_session_factory() as session:
                result = await session.execute(select(UserModel).filter(UserModel.email == email))
                user = result.scalars().first()
                if not user:
                    return None

                user_entity = UserEntity(
                    id=user.user_id,
                    email=user.email,
                    password_hash=user.password_hash,
                    auth_provider=user.auth_provider,
                    is_email_verified=user.is_email_verified,
                    name=user.name or "",
                    phone=user.phone or "",
                    image_url=user.image_url or "",
                    is_profile_created=user.is_profile_created,
                    profile_colour=user.profile_colour or "",
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                )
                return UserAggregate(user=user_entity)

        except Exception as e:
            self.logger.error(f"Error getting user by email: {e!s}")
            raise HTTPException(status_code=500, detail="Failed to fetch user by email")

    async def get_user_by_id(self, user_id: str) -> UserAggregate | None:
        try:
            async with self.db_session_factory() as session:
                result = await session.execute(select(UserModel).filter(UserModel.user_id == user_id))
                user = result.scalars().first()
                if not user:
                    return None

                user_entity = UserEntity(
                    id=user.user_id,
                    email=user.email,
                    password_hash=user.password_hash,
                    auth_provider=user.auth_provider,
                    is_email_verified=user.is_email_verified,
                    name=user.name or "",
                    phone=user.phone or "",
                    image_url=user.image_url or "",
                    is_profile_created=user.is_profile_created,
                    profile_colour=user.profile_colour or "",
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                )
                return UserAggregate(user=user_entity)

        except Exception as e:
            self.logger.error(f"Error getting user by ID: {e!s}")
            raise HTTPException(status_code=500, detail="Failed to fetch user by ID")

    async def update_email_verification(self, user_id: str, is_verified: bool) -> UserAggregate:
        try:
            async with self.db_session_factory() as session:
                async with session.begin():
                    result = await session.execute(select(UserModel).filter(UserModel.user_id == user_id))
                    user = result.scalars().first()
                    if not user:
                        raise HTTPException(status_code=404, detail="User not found")

                    user.is_email_verified = is_verified

                await session.refresh(user)

                user_entity = UserEntity(
                    id=user.user_id,
                    email=user.email,
                    password_hash=user.password_hash,
                    auth_provider=user.auth_provider,
                    is_email_verified=user.is_email_verified,
                    name=user.name or "",
                    phone=user.phone or "",
                    image_url=user.image_url or "",
                    is_profile_created=user.is_profile_created,
                    profile_colour=user.profile_colour or "",
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                )
                return UserAggregate(user=user_entity, events=["EmailVerificationUpdated"])

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error updating email verification: {e!s}")
            raise HTTPException(status_code=500, detail="Failed to update email verification")

    async def update_user_password(self, user_id: str, password_hash: str) -> UserAggregate:
        try:
            async with self.db_session_factory() as session:
                async with session.begin():
                    result = await session.execute(select(UserModel).filter(UserModel.user_id == user_id))
                    user = result.scalars().first()
                    if not user:
                        raise HTTPException(status_code=404, detail="User not found")

                    if user.auth_provider != "email":
                        raise HTTPException(
                            status_code=400,
                            detail=f"Cannot update password for {user.auth_provider} authentication"
                        )

                    user.password_hash = password_hash

                await session.refresh(user)

                user_entity = UserEntity(
                    id=user.user_id,
                    email=user.email,
                    password_hash=user.password_hash,
                    auth_provider=user.auth_provider,
                    is_email_verified=user.is_email_verified,
                    name=user.name or "",
                    phone=user.phone or "",
                    image_url=user.image_url or "",
                    is_profile_created=user.is_profile_created,
                    profile_colour=user.profile_colour or "",
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                )

                return UserAggregate(user=user_entity, events=["PasswordUpdated"])

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error updating user password: {e!s}")
            raise HTTPException(status_code=500, detail="Failed to update password")

    async def delete_user(self, user_id: str) -> bool:
        try:
            async with self.db_session_factory() as session:
                async with session.begin():
                    result = await session.execute(select(UserModel).filter(UserModel.user_id == user_id))
                    user = result.scalars().first()
                    if not user:
                        raise HTTPException(status_code=404, detail="User not found")

                    await session.delete(user)

            return True

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting user: {e!s}")
            raise HTTPException(status_code=500, detail="Failed to delete user")

    async def delete_all_user_conversations(self, user_id: str) -> None:
        """Delete all conversations and messages for a user"""
        try:
            async with self.db_session_factory() as session:
                async with session.begin():
                    # First get all conversation IDs for this user
                    conv_result = await session.execute(
                        select(ConversationModel.id).filter(ConversationModel.user_id == user_id)
                    )
                    conversation_ids = [row[0] for row in conv_result.fetchall()]

                    # Delete all messages for these conversations
                    if conversation_ids:
                        await session.execute(
                            delete(MessageModel).where(MessageModel.conversation_id.in_(conversation_ids))
                        )

                    # Delete all conversations for this user
                    await session.execute(
                        delete(ConversationModel).where(ConversationModel.user_id == user_id)
                    )

            self.logger.info(f"Deleted all conversations and messages for user {user_id}")

        except Exception as e:
            self.logger.error(f"Error deleting user conversations: {e!s}")
            raise HTTPException(status_code=500, detail="Failed to delete user conversations")
