import hashlib
import uuid
from datetime import datetime,timedelta,timezone

from typing import Any

from fastapi import Response
import jwt
from pwdlib import PasswordHash
import secrets

from projecthub_backend.core.config import settings

password_hasher = PasswordHash.recommended()

def hash_password(password: str) -> str:
    return password_hasher.hash(password=password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    return password_hasher.verify(plain_password, hashed_password)

def hash_token(token:str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload:dict[str: Any] = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": expire
    }

    return jwt.encode(payload,settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def create_refresh_token(user_id: uuid.UUID, jti: uuid.UUID, family_id: uuid.UUID) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "jti": str(jti),
        "family_id": str(family_id),
        "type": "refresh",
        "iat": now,
        "exp": expire,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, expire

def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def generate_opaque_token() -> str:
    """Generates a cryptographically secure random URL-safe token."""
    return secrets.token_urlsafe(32)

def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    is_prod = not settings.DEBUG
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/v1/auth",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/api/v1/auth")
