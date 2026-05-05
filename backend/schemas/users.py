from uuid import UUID
from pydantic import BaseModel, Field, field_validator

class UserCreate(BaseModel):
    username: str = Field(
        ..., 
        min_length=3, 
        max_length=50, 
        examples=["alireza_99"]
    )
    email: str = Field(
        ..., 
        pattern=r'^\S+@\S+\.\S+$', 
        examples=["user@example.com"]
    )
    password: str = Field(
        ..., 
        min_length=6, max_length=72,
        examples=["secret_pass"]
    )

    @field_validator('username')
    @classmethod
    def validate_username(cls, value: str) -> str:
        # This allows letters, numbers, and underscores
        if not all(char.isalnum() or char == '_' for char in value):
            raise ValueError('Username must be alphanumeric (underscores allowed)')
        return value


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50, examples=["alireza_99"])
    email: str | None = Field(default=None, pattern=r'^\S+@\S+\.\S+$', examples=["user@example.com"])
    password: str | None = Field(default=None, min_length=6, max_length=72, examples=["new_secret"])

    @field_validator('username')
    @classmethod
    def validate_username(cls, value: str | None) -> str | None:
        if value and not all(char.isalnum() or char == '_' for char in value):
            raise ValueError('Username must be alphanumeric (underscores allowed)')
        return value


class ShowUser(BaseModel):
    id: int
    uuid: UUID
    username: str
    email: str

    class Config:
        from_attributes = True