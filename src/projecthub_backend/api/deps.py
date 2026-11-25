import uuid

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from projecthub_backend.core.database import get_db
from projecthub_backend.core.security import decode_token
from projecthub_backend.models.user import User

# Tells FastAPI & Swagger UI to look for "Authorization: Bearer <token>"
bearer_schema = HTTPBearer()


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_schema),
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get("access_token")
    if not token and credentials:
        token = credentials.credentials

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )

    if not token:
        raise credentials_exception

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise credentials_exception
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise credentials_exception
        user_id = uuid.UUID(user_id_str)
    except (jwt.PyJWTError, ValueError):
        raise credentials_exception

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive or non-existent user",
        )
    return user
