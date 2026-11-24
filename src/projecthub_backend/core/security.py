import hashlib
import uuid
from datetime import datetime,timedelta,timezone

from typing import Any

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
