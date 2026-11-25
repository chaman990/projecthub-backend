import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from projecthub_backend.api.deps import get_current_user
from projecthub_backend.core.config import settings
from projecthub_backend.core.database import get_db
from projecthub_backend.core.email import (
    send_password_reset_email,
    send_verification_email,
)
from projecthub_backend.core.security import (
    clear_auth_cookies,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    set_auth_cookies,
    verify_password,
)
from projecthub_backend.models.user import (
    EmailVerificationToken,
    PasswordResetToken,
    RefreshToken,
    User,
)
from projecthub_backend.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    RefreshTokenRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UpdateProfileRequest,
    UserResponse,
    VerifyEmailRequest,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _issue_session_tokens(
    db: Session,
    user: User,
    request: Request,
    family_id: uuid.UUID | None = None,
) -> tuple[str, str, RefreshToken]:
    access_token = create_access_token(user.id)
    new_jti = uuid.uuid4()
    token_family = family_id or uuid.uuid4()
    raw_refresh, expires_at = create_refresh_token(user.id, new_jti, token_family)

    db_token = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        jti=new_jti,
        family_id=token_family,
        expires_at=expires_at,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    db.add(db_token)
    db.flush()
    return access_token, raw_refresh, db_token


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse:
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
    db.flush()

    access_token, refresh_token, _ = _issue_session_tokens(db, user, request)
    db.commit()
    db.refresh(user)

    set_auth_cookies(response, access_token, refresh_token)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=UserResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse:
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
    access_token, refresh_token, _ = _issue_session_tokens(db, user, request)
    db.commit()
    db.refresh(user)

    set_auth_cookies(response, access_token, refresh_token)
    return UserResponse.model_validate(user)


@router.post("/refresh", response_model=UserResponse)
def refresh_tokens(
    request: Request,
    response: Response,
    payload: RefreshTokenRequest | None = None,
    db: Session = Depends(get_db),
) -> UserResponse:
    raw_refresh = request.cookies.get("refresh_token") or (
        payload.refresh_token if payload else None
    )
    if not raw_refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing"
        )

    try:
        decoded = decode_token(raw_refresh)
        if decoded.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type"
            )
        jti = uuid.UUID(decoded["jti"])
    except (jwt.PyJWTError, KeyError, ValueError):
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
    if not stored or stored.token_hash != hash_token(raw_refresh):
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not recognized",
        )

    now = datetime.now(timezone.utc)

    if stored.revoked_at is not None:
        db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == stored.family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        db.commit()
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token reuse detected; session revoked",
        )

    if stored.expires_at <= now:
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired"
        )

    user = db.get(User, stored.user_id)
    if not user or not user.is_active:
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User inactive or not found",
        )

    new_access, new_refresh, new_db_token = _issue_session_tokens(
        db, user, request, family_id=stored.family_id
    )
    stored.revoked_at = now
    stored.replaced_by_id = new_db_token.id
    db.commit()

    set_auth_cookies(response, new_access, new_refresh)
    return UserResponse.model_validate(user)


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    response: Response,
    payload: LogoutRequest | None = None,
    db: Session = Depends(get_db),
) -> MessageResponse:
    raw_refresh = request.cookies.get("refresh_token") or (
        payload.refresh_token if payload else None
    )
    if raw_refresh:
        try:
            decoded = decode_token(raw_refresh)
            jti = uuid.UUID(decoded["jti"])
            stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
            if stored and stored.revoked_at is None:
                stored.revoked_at = datetime.now(timezone.utc)
                db.commit()
        except (jwt.PyJWTError, KeyError, ValueError):
            pass

    clear_auth_cookies(response)
    return MessageResponse(message="Logged out successfully")


@router.post("/logout-all", response_model=MessageResponse)
def logout_all(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    now = datetime.now(timezone.utc)
    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == current_user.id, RefreshToken.revoked_at.is_(None)
        )
        .values(revoked_at=now)
    )
    db.commit()
    clear_auth_cookies(response)
    return MessageResponse(message="Logged out from all devices")


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse)
def update_me(
    payload: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    if payload.full_name is not None:
        current_user.full_name = payload.full_name.strip()
    if payload.avatar_url is not None:
        current_user.avatar_url = payload.avatar_url
    db.commit()
    db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    now = datetime.now(timezone.utc)
    current_user.password_hash = hash_password(payload.new_password)
    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == current_user.id, RefreshToken.revoked_at.is_(None)
        )
        .values(revoked_at=now)
    )
    db.commit()
    clear_auth_cookies(response)
    return MessageResponse(
        message="Password updated successfully. Please log in again."
    )


@router.post("/send-verification", response_model=MessageResponse)
def send_verification(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    if current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email is already verified"
        )

    raw_token = generate_opaque_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    db.add(
        EmailVerificationToken(
            user_id=current_user.id,
            token_hash=hash_token(raw_token),
            expires_at=expires_at,
        )
    )
    db.commit()

    background_tasks.add_task(
        send_verification_email, current_user.email, current_user.full_name, raw_token
    )
    return MessageResponse(
        message="Verification email sent",
        dev_token=raw_token if settings.DEBUG else None,
    )


@router.post("/verify-email", response_model=MessageResponse)
def verify_email(
    payload: VerifyEmailRequest, db: Session = Depends(get_db)
) -> MessageResponse:
    now = datetime.now(timezone.utc)
    record = db.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == hash_token(payload.token),
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.expires_at > now,
        )
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    user = db.get(User, record.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    record.used_at = now
    user.is_verified = True
    db.commit()
    return MessageResponse(message="Email verified successfully")


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> MessageResponse:
    user = db.scalar(
        select(User).where(
            User.email == payload.email.lower(), User.is_active.is_(True)
        )
    )
    raw_token: str | None = None
    if user:
        raw_token = generate_opaque_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=expires_at,
        )
    )
    db.commit()
    background_tasks.add_task(
        send_password_reset_email, user.email, user.full_name, raw_token
    )
    return MessageResponse(
        message="If that email exists, a password reset link has been sent",
        dev_token=raw_token if settings.DEBUG else None,
    )


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(
    payload: ResetPasswordRequest, db: Session = Depends(get_db)
) -> MessageResponse:
    now = datetime.now(timezone.utc)
    record = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_token(payload.token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    user = db.get(User, record.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    record.used_at = now
    user.password_hash = hash_password(payload.new_password)
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    db.commit()
    return MessageResponse(message="Password reset successfully")
