from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

from core.security import MIN_PASSWORD_LENGTH


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)
    email: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    access_expires_in: int
    refresh_expires_in: int


class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)
    email: str | None = None
    is_admin: bool = False


class NameUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)


class UserUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    is_admin: bool | None = None
    password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH)


class ShowUser(BaseModel):
    uuid: UUID
    username: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    is_active: bool
    is_admin: bool
    created_at: datetime | None = None

    class Config:
        from_attributes = True
