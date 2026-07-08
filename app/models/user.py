"""Pydantic models (DTOs) for users and authentication."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    """Payload for registering a new user."""

    username: str = Field(min_length=3, max_length=32)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def username_no_whitespace(cls, value: str) -> str:
        if value != value.strip() or " " in value:
            raise ValueError("username must not contain whitespace")
        return value


class LoginRequest(BaseModel):
    """Payload for logging in."""

    username: str
    password: str


class UserOut(BaseModel):
    """Public-facing user representation (never includes password_hash)."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    username: str
    email: EmailStr
    created_at: datetime


class SessionOut(BaseModel):
    """A newly-created session, as returned by the auth service."""

    model_config = ConfigDict(frozen=True)

    token: str
    user: UserOut
    expires_at: datetime
