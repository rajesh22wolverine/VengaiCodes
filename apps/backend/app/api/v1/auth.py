# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Authentication API Routes
#  api/v1/auth.py — Signup, Login, OTP, Password Reset, Sessions
# ═══════════════════════════════════════════════════════════════

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.redis import blocklist_token, is_token_blocklisted
from app.core.security import (
    create_token_pair,
    decode_refresh_token,
    decode_token,
    hash_password,
    mask_email,
    mask_mobile,
    verify_password,
)
from app.models.user import OTPRecord, User, UserStatus, VerificationStatus
from app.schemas.auth import (
    ErrorResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SendOTPRequest,
    SendOTPResponse,
    SignupRequest,
    SignupResponse,
    TokenRefreshRequest,
    TokenRefreshResponse,
    UserResponse,
    VerifyOTPRequest,
    VerifyOTPResponse,
    VerifySessionRequest,
    VerifySessionResponse,
    validate_indian_mobile,
)
from app.services.msg91_service import send_otp_sms, MSG91Error
from app.utils.otp import create_otp_record, verify_otp_code

logger = logging.getLogger("vengaicode.auth")

router = APIRouter()

# Points at /auth/token so Swagger's Authorize button works automatically
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


# ═══════════════════════════════════════════════════════════════
#  Dependency — Get Current User
#  Used by other routers to protect endpoints
# ═══════════════════════════════════════════════════════════════
async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Resolve the current authenticated user from a JWT access token.
    Raises 401 if token is missing, invalid, expired, or blocklisted.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if token is None:
        raise credentials_exception

    try:
        token_data = decode_token(token, expected_type="access")
    except JWTError:
        raise credentials_exception

    if await is_token_blocklisted(token):
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == token_data.user_id))
    user = result.scalar_one_or_none()

    if user is None or user.deleted_at is not None:
        raise credentials_exception

    if user.status in (UserStatus.BANNED, UserStatus.SUSPENDED):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been restricted. "
            "Please contact support@vengaicode.com",
        )

    return user


async def get_current_active_user(
    user: User = Depends(get_current_user),
) -> User:
    """Require an active, non-restricted user."""
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive.",
        )
    return user


# ═══════════════════════════════════════════════════════════════
#  POST /auth/token — Swagger UI OAuth2 compatibility endpoint
#  Swagger's Authorize button sends username+password as form data.
#  This endpoint accepts that format, validates credentials, and
#  returns a token — so Swagger auto-attaches it to all requests.
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/token",
    summary="Get token (Swagger UI Authorize button)",
    include_in_schema=True,
    tags=["Authentication"],
)
async def get_token_for_swagger(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    OAuth2 password flow endpoint for Swagger UI's Authorize button.

    Enter your username and password in Swagger's Authorize dialog
    and all protected endpoints will automatically use the token.
    This is a convenience endpoint for API testing — the main login
    endpoint is POST /auth/login (JSON body).
    """
    result = await db.execute(
        select(User).where(
            or_(
                User.username == form_data.username,
                User.email == form_data.username,
            )
        )
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.status == UserStatus.PENDING_VERIFICATION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in.",
        )

    if user.status in (UserStatus.BANNED, UserStatus.SUSPENDED):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been restricted. Contact support@vengaicode.com",
        )

    access_token, _, expires_in = create_token_pair(
        user_id=user.id,
        username=user.username,
        email=user.email,
        tier=user.tier.value if hasattr(user.tier, "value") else user.tier,
    )

    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    # Must return exactly this shape for OAuth2PasswordBearer to work
    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


# ═══════════════════════════════════════════════════════════════
#  POST /auth/signup
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/signup",
    response_model=SignupResponse,
    responses={409: {"model": ErrorResponse}},
    summary="Register a new VengaiCode account",
)
async def signup(payload: SignupRequest, db: AsyncSession = Depends(get_db)):
    """
    Create a new user account.

    Account is created in PENDING_VERIFICATION status.
    An OTP is sent to the user's email for verification.
    User must verify email (and later mobile) before full access.
    """
    result = await db.execute(
        select(User).where(
            or_(
                User.email == payload.email,
                User.username == payload.username,
                User.mobile == payload.mobile,
            )
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        if existing.email == payload.email:
            field = "email address"
        elif existing.username == payload.username:
            field = "username"
        else:
            field = "mobile number"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with this {field} already exists.",
        )

    new_user = User(
        full_name=payload.full_name,
        username=payload.username,
        email=payload.email,
        mobile=payload.mobile,
        hashed_password=hash_password(payload.password),
        status=UserStatus.PENDING_VERIFICATION,
        verification_status=VerificationStatus.NOT_STARTED,
        tier="free",
        projects_limit=settings.PRICING_FREE_PROJECTS,
        revenue_sharing_agreed=False,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    try:
        plain_otp, _ = await create_otp_record(
            db, target=new_user.email, otp_type="email",
            purpose="signup", user_id=new_user.id,
        )
        print(f"[DEV] Signup OTP for {new_user.email}: {plain_otp}", flush=True)
    except ValueError as e:
        logger.warning(f"OTP creation rate-limited for new user: {e}")

    return SignupResponse(
        message=(
            "Welcome to VengaiCode! 🐯 We've sent a verification code "
            "to your email. Please verify to continue."
        ),
        user_id=new_user.id,
        next_step="verify_email",
        otp_sent_to=mask_email(new_user.email),
    )


# ═══════════════════════════════════════════════════════════════
#  POST /auth/send-otp
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/send-otp",
    response_model=SendOTPResponse,
    responses={429: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Send OTP to email or mobile",
)
async def send_otp(payload: SendOTPRequest, db: AsyncSession = Depends(get_db)):
    """
    Send a 6-digit OTP to the given email or mobile number.

    Used for: login (2FA), signup verification, mobile verification,
    password reset, licence recovery.
    """
    target = payload.target.strip()

    if payload.otp_type == "mobile":
        try:
            target = validate_indian_mobile(target)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    if payload.purpose in ("login", "password_reset", "licence_recovery"):
        lookup_field = User.email if payload.otp_type == "email" else User.mobile
        result = await db.execute(select(User).where(lookup_field == target))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="If an account exists with these details, an OTP has been sent.",
            )
        user_id = user.id
    else:
        user_id = None

    try:
        plain_otp, otp_record = await create_otp_record(
            db, target=target, otp_type=payload.otp_type,
            purpose=payload.purpose, user_id=user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    if payload.otp_type == "mobile":
        try:
            await send_otp_sms(target, plain_otp)
        except MSG91Error as e:
            logger.error(f"Failed to send OTP SMS: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to send OTP. Please try again shortly.",
            )
    else:
        print(f"[DEV] OTP for {target}: {plain_otp}", flush=True)

    mask_fn = mask_email if payload.otp_type == "email" else mask_mobile
    return SendOTPResponse(
        message="OTP sent successfully! 🐯",
        otp_sent_to=mask_fn(target),
        expires_in_minutes=settings.MSG91_OTP_EXPIRE_MINUTES,
        resend_after_seconds=60,
    )


# ═══════════════════════════════════════════════════════════════
#  POST /auth/verify-otp
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/verify-otp",
    response_model=VerifyOTPResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Verify an OTP code",
)
async def verify_otp(payload: VerifyOTPRequest, db: AsyncSession = Depends(get_db)):
    """
    Verify a 6-digit OTP.

    On success for 'signup'/'verify' purposes — marks email/mobile
    verified and (for signup) activates the account and returns tokens.

    On success for 'login' purpose — returns tokens (completes 2FA login).
    """
    target = payload.target.strip()
    if payload.otp_type == "mobile":
        try:
            target = validate_indian_mobile(target)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    success, message = await verify_otp_code(db, target, payload.otp, payload.purpose)

    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    lookup_field = User.email if payload.otp_type == "email" else User.mobile
    result = await db.execute(select(User).where(lookup_field == target))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )

    if payload.purpose in ("signup", "verify"):
        if payload.otp_type == "email" and not user.email_verified:
            user.email_verified = True
            user.email_verified_at = datetime.now(timezone.utc)
            user.verification_status = VerificationStatus.EMAIL_VERIFIED
        elif payload.otp_type == "mobile" and not user.mobile_verified:
            user.mobile_verified = True
            user.mobile_verified_at = datetime.now(timezone.utc)
            if user.email_verified:
                user.verification_status = VerificationStatus.MOBILE_VERIFIED

        if user.email_verified and user.status == UserStatus.PENDING_VERIFICATION:
            user.status = UserStatus.ACTIVE

        await db.commit()
        await db.refresh(user)

        access_token, refresh_token, expires_in = create_token_pair(
            user_id=user.id,
            username=user.username,
            email=user.email,
            tier=user.tier.value if hasattr(user.tier, "value") else user.tier,
        )
        user.last_login = datetime.now(timezone.utc)
        await db.commit()

        return VerifyOTPResponse(
            message="Verified! Welcome to VengaiCode 🐯",
            verified=True,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            user=UserResponse.from_db(user),
        )

    if payload.purpose == "login":
        access_token, refresh_token, expires_in = create_token_pair(
            user_id=user.id,
            username=user.username,
            email=user.email,
            tier=user.tier.value if hasattr(user.tier, "value") else user.tier,
        )
        user.last_login = datetime.now(timezone.utc)
        user.failed_login_attempts = 0
        await db.commit()

        return VerifyOTPResponse(
            message="Login successful! Welcome back 🐯",
            verified=True,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            user=UserResponse.from_db(user),
        )

    return VerifyOTPResponse(message=message, verified=True)


# ═══════════════════════════════════════════════════════════════
#  POST /auth/login
# ═══════════════════════════════════════════════════════════════
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Login with username/email and password",
)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticate with username/email + password.

    If account is locked due to too many failed attempts, returns 403.
    On success, returns JWT access + refresh tokens.
    """
    identifier = payload.username_or_email

    result = await db.execute(
        select(User).where(
            or_(User.username == identifier, User.email == identifier)
        )
    )
    user = result.scalar_one_or_none()

    generic_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username/email or password.",
    )

    if user is None or user.deleted_at is not None:
        raise generic_error

    if user.lockout_until and user.lockout_until > datetime.now(timezone.utc):
        minutes_left = int((user.lockout_until - datetime.now(timezone.utc)).total_seconds() / 60) + 1
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Too many failed login attempts. "
                f"Please try again in {minutes_left} minute(s)."
            ),
        )

    if not verify_password(payload.password, user.hashed_password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            user.lockout_until = datetime.now(timezone.utc) + timedelta(
                minutes=LOCKOUT_MINUTES
            )
            user.failed_login_attempts = 0
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Too many failed login attempts. "
                    f"Account locked for {LOCKOUT_MINUTES} minutes."
                ),
            )
        await db.commit()
        raise generic_error

    if user.status == UserStatus.PENDING_VERIFICATION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in.",
        )
    if user.status in (UserStatus.BANNED, UserStatus.SUSPENDED):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Your account has been restricted"
                + (f": {user.restriction_reason}" if user.restriction_reason else ".")
                + " Contact support@vengaicode.com to appeal."
            ),
        )

    user.failed_login_attempts = 0
    user.lockout_until = None
    user.last_login = datetime.now(timezone.utc)

    access_token, refresh_token, expires_in = create_token_pair(
        user_id=user.id,
        username=user.username,
        email=user.email,
        tier=user.tier.value if hasattr(user.tier, "value") else user.tier,
        remember_me=payload.remember_me,
    )

    await db.commit()
    await db.refresh(user)

    return LoginResponse(
        message="Welcome back! Baby Tiger missed you 🐯",
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user=UserResponse.from_db(user),
    )


# ═══════════════════════════════════════════════════════════════
#  POST /auth/refresh-token
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/refresh-token",
    response_model=TokenRefreshResponse,
    responses={401: {"model": ErrorResponse}},
    summary="Get a new access token using a refresh token",
)
async def refresh_token(
    payload: TokenRefreshRequest, db: AsyncSession = Depends(get_db)
):
    """Exchange a valid refresh token for a new access token."""
    try:
        user_id = decode_refresh_token(payload.refresh_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token. Please log in again.",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found."
        )

    if user.status in (UserStatus.BANNED, UserStatus.SUSPENDED):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been restricted.",
        )

    access_token, _, expires_in = create_token_pair(
        user_id=user.id,
        username=user.username,
        email=user.email,
        tier=user.tier.value if hasattr(user.tier, "value") else user.tier,
    )

    return TokenRefreshResponse(access_token=access_token, expires_in=expires_in)


# ═══════════════════════════════════════════════════════════════
#  POST /auth/forgot-password
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    summary="Request a password reset OTP",
)
async def forgot_password(
    payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """
    Send a password reset OTP to the user's email.

    Always returns success message regardless of whether the account
    exists — prevents account enumeration.
    """
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    generic_response = ForgotPasswordResponse(
        message=(
            "If an account exists with this email, "
            "a password reset code has been sent. 🐯"
        ),
        otp_sent_to=mask_email(payload.email),
    )

    if user is None or user.deleted_at is not None:
        return generic_response

    try:
        plain_otp, _ = await create_otp_record(
            db, target=user.email, otp_type="email",
            purpose="password_reset", user_id=user.id,
        )
        print(f"[DEV] Password reset OTP for {user.email}: {plain_otp}", flush=True)
    except ValueError:
        pass

    return generic_response


# ═══════════════════════════════════════════════════════════════
#  POST /auth/reset-password
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Reset password using OTP",
)
async def reset_password(
    payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """Reset password after verifying OTP sent to email."""
    success, message = await verify_otp_code(
        db, target=payload.email, otp=payload.otp, purpose="password_reset"
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    user.hashed_password = hash_password(payload.new_password)
    user.failed_login_attempts = 0
    user.lockout_until = None
    await db.commit()

    return ResetPasswordResponse()


# ═══════════════════════════════════════════════════════════════
#  GET /auth/verify-session
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/verify-session",
    response_model=VerifySessionResponse,
    summary="Verify a session token (used on app startup)",
)
async def verify_session_get(
    user: User = Depends(get_current_active_user),
):
    """
    Verify the current session is valid and return user data.
    Desktop app calls this on startup to restore session.
    """
    return VerifySessionResponse(valid=True, user=UserResponse.from_db(user))


# ═══════════════════════════════════════════════════════════════
#  POST /auth/logout
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Logout — blocklists the current access token",
)
async def logout(
    token: str | None = Depends(oauth2_scheme),
    user: User = Depends(get_current_active_user),
):
    """
    Logout the current session.

    Blocklists the access token in Redis until it would naturally
    expire, preventing reuse even though JWTs are normally stateless.
    """
    if token:
        try:
            token_data = decode_token(token, expected_type="access")
            ttl = max(
                1,
                int((token_data.exp - datetime.now(timezone.utc)).total_seconds())
                if token_data.exp
                else settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            )
            await blocklist_token(token, ttl_seconds=ttl)
        except JWTError:
            pass

    return LogoutResponse()