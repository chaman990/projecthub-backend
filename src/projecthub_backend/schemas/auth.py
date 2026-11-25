import uuid
from datetime import datetime 
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

class RegisterRequest(BaseModel):
    full_name:str = Field(..., min_length=2,max_length=150)
    email: EmailStr
    password:str = Field(...,min_length=8, max_length=120)

class LoginRequest(BaseModel):
    email: EmailStr
    password:str = Field(..., min_length=8, max_length=128)

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: EmailStr
    platform_role: str
    is_active: bool
    is_verified: bool
    avatar_url: Optional[str] = None
    last_login_at: Optional[datetime] = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class MessageResponse(BaseModel):
    message: str


class VerifyEmailRequest(BaseModel):
    token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)

class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=150)
    avatar_url: Optional[str] = None

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)


class MessageResponse(BaseModel):
    message: str
    dev_token: Optional[str] = None
