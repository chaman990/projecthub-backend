import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
import jwt
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from projecthub_backend.core.database import get_db
from projecthub_backend.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password
)
from projecthub_backend.models.user import RefreshToken, User
from projecthub_backend.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse
)
from projecthub_backend.api.deps import get_current_user


router = APIRouter(prefix='/auth', tags=['Authentication'])


def _create_session_token(db:Session, user:User, request: Request, family_id: uuid.UUID | None = None,) -> tuple[str, str]:
    access_token = create_access_token(user.id)
    jti = uuid.uuid4()
    family_id = uuid.uuid4()
    token_family = family_id or uuid.uuid4()
    raw_refresh, expires_at = create_refresh_token(user_id=user.id, jti=jti, family_id=family_id)
    db_token = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        jti=jti,
        family_id=token_family,
        expires_at=expires_at,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    db.add(db_token)
    return access_token, raw_refresh, db_token

@router.post('/register', status_code=status.HTTP_201_CREATED, response_model=TokenResponse)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    existing_user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )
    user = User(
        full_name=payload.full_name.strip(),
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        last_login_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()  # Generates user.id before creating refresh_token

    access_token, refresh_token, _  = _create_session_token(db, user, request)
    db.commit()
    db.refresh(user)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )

@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    user.last_login_at = datetime.now(timezone.utc)
    access_token, refresh_token , _  = _create_session_token(db, user, request)
    db.commit()
    db.refresh(user)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )

@router.get('/me', response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)

@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(payload: RefreshTokenRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        decoded = decode_token(payload.refresh_token)
        if decoded.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        jti = uuid.UUID(decoded["jti"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
    if not stored or stored.token_hash != hash_token(payload.refresh_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not recognized")

    now = datetime.now(timezone.utc)

    # Replay detection: if already revoked, revoke the whole family
    if stored.revoked_at is not None:
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == stored.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token reuse detected; session revoked")

    if stored.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    user = db.get(User, stored.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive or not found")

    access_token, new_refresh, new_db_token = _create_session_token(
        db, user, request, family_id=stored.family_id
    )
    stored.revoked_at = now
    stored.replaced_by_id = new_db_token.id
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        user=UserResponse.model_validate(user),
    )


@router.post("/logout", response_model=MessageResponse)
def logout(payload: LogoutRequest, db: Session = Depends(get_db)) -> MessageResponse:
    try:
        decoded = decode_token(payload.refresh_token)
        jti = uuid.UUID(decoded["jti"])
        stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
        if stored and stored.revoked_at is None:
            stored.revoked_at = datetime.now(timezone.utc)
            db.commit()
    except (jwt.PyJWTError, KeyError, ValueError):
        pass

    return MessageResponse(message="Logged out successfully")


@router.post("/logout-all", response_model=MessageResponse)
def logout_all(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MessageResponse:
    now = datetime.now(timezone.utc)
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == current_user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    db.commit()
    return MessageResponse(message="Logged out from all devices")
