# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Authentication Schemas
#  schemas/auth.py — Pydantic request/response schemas for auth
#  All inputs validated, all outputs typed
# ═══════════════════════════════════════════════════════════════

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator, model_validator, Field


# ───────────────────────────────────────────────
#  Validators (reusable)
# ───────────────────────────────────────────────
def validate_password_strength(password: str) -> str:
    """
    Enforce strong passwords for VengaiCode users.
    Requirements:
    - Minimum 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 digit
    - At least 1 special character
    """
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one number")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=\[\]\\;'/`~]", password):
        raise ValueError("Password must contain at least one special character")
    return password


def validate_username(username: str) -> str:
    """
    Enforce valid VengaiCode usernames.
    Requirements:
    - 3-30 characters
    - Only letters, numbers, underscores, hyphens
    - Cannot start or end with underscore/hyphen
    """
    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters long")
    if len(username) > 30:
        raise ValueError("Username cannot exceed 30 characters")
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]*[a-zA-Z0-9]$", username):
        raise ValueError(
            "Username can only contain letters, numbers, underscores and hyphens. "
            "Cannot start or end with underscore or hyphen."
        )
    # Reserved usernames
    reserved = {"admin", "vengaicode", "tiger", "baby_tiger", "support", "api", "root"}
    if username.lower() in reserved:
        raise ValueError(f"Username '{username}' is reserved")
    return username.lower()


def validate_indian_mobile(mobile: str) -> str:
    """Validate Indian mobile number format."""
    mobile = mobile.strip().replace(" ", "").replace("-", "")
    if mobile.startswith("+91"):
        mobile = mobile[3:]
    elif mobile.startswith("91") and len(mobile) == 12:
        mobile = mobile[2:]
    if not re.match(r"^[6-9]\d{9}$", mobile):
        raise ValueError(
            "Please enter a valid Indian mobile number (10 digits starting with 6-9)"
        )
    return f"+91{mobile}"


# ───────────────────────────────────────────────
#  Signup Schemas
# ───────────────────────────────────────────────
class SignupRequest(BaseModel):
    """User registration request."""
    full_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="User's full name",
        examples=["Kalki Kumar"],
    )
    username: str = Field(
        ...,
        min_length=3,
        max_length=30,
        description="Unique username",
        examples=["kalki_builds"],
    )
    email: EmailStr = Field(
        ...,
        description="Valid email address",
        examples=["kalki@example.com"],
    )
    mobile: str = Field(
        ...,
        description="Indian mobile number",
        examples=["9876543210"],
    )
    password: str = Field(
        ...,
        min_length=8,
        description="Strong password",
    )
    confirm_password: str = Field(
        ...,
        description="Must match password",
    )
    agree_to_terms: bool = Field(
        ...,
        description="Must agree to Terms of Service and Privacy Policy",
    )

    @field_validator("username")
    @classmethod
    def check_username(cls, v: str) -> str:
        return validate_username(v)

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return validate_password_strength(v)

    @field_validator("mobile")
    @classmethod
    def check_mobile(cls, v: str) -> str:
        return validate_indian_mobile(v)

    @field_validator("full_name")
    @classmethod
    def check_full_name(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^[a-zA-Z\s\.']+$", v):
            raise ValueError("Full name can only contain letters, spaces, dots and apostrophes")
        return v

    @model_validator(mode="after")
    def passwords_match(self) -> "SignupRequest":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self

    @model_validator(mode="after")
    def must_agree_to_terms(self) -> "SignupRequest":
        if not self.agree_to_terms:
            raise ValueError(
                "You must agree to VengaiCode's Terms of Service and Privacy Policy to continue"
            )
        return self


class SignupResponse(BaseModel):
    """Response after successful signup initiation."""
    success: bool = True
    message: str
    user_id: str
    next_step: str
    # "verify_email" or "verify_mobile"
    otp_sent_to: str
    # Masked email/mobile e.g. "ka***@example.com" or "+91 98***43210"


# ───────────────────────────────────────────────
#  Login Schemas
# ───────────────────────────────────────────────
class LoginRequest(BaseModel):
    """User login request."""
    username_or_email: str = Field(
        ...,
        description="Username or email address",
        examples=["kalki_builds"],
    )
    password: str = Field(
        ...,
        description="Account password",
    )
    remember_me: bool = Field(
        default=False,
        description="If true, session lasts 30 days instead of 30 minutes",
    )

    @field_validator("username_or_email")
    @classmethod
    def check_identifier(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("Please enter your username or email")
        return v


class LoginResponse(BaseModel):
    """Response after successful login."""
    success: bool = True
    message: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    # Seconds until access token expires
    user: "UserResponse"
    requires_otp: bool = False
    # True if second factor OTP is required
    otp_type: Optional[str] = None
    # "email" or "mobile"


# ───────────────────────────────────────────────
#  OTP Schemas
# ───────────────────────────────────────────────
class SendOTPRequest(BaseModel):
    """Request to send OTP to email or mobile."""
    target: str = Field(
        ...,
        description="Email address or mobile number to send OTP to",
    )
    otp_type: str = Field(
        ...,
        description="Type of OTP target",
        pattern="^(email|mobile)$",
    )
    purpose: str = Field(
        ...,
        description="Purpose of OTP",
        pattern="^(login|signup|verify|password_reset|licence_recovery)$",
    )

    @field_validator("target")
    @classmethod
    def check_target(cls, v: str, info) -> str:
        # Will be validated against otp_type in route handler
        return v.strip()


class SendOTPResponse(BaseModel):
    """Response after OTP is sent."""
    success: bool = True
    message: str
    otp_sent_to: str
    # Masked target e.g. "ka***@example.com"
    expires_in_minutes: int = 10
    resend_after_seconds: int = 60


class VerifyOTPRequest(BaseModel):
    """Request to verify OTP code."""
    target: str = Field(
        ...,
        description="Email or mobile the OTP was sent to",
    )
    otp: str = Field(
        ...,
        min_length=6,
        max_length=6,
        description="6-digit OTP code",
        pattern="^[0-9]{6}$",
    )
    otp_type: str = Field(
        ...,
        pattern="^(email|mobile)$",
    )
    purpose: str = Field(
        ...,
        pattern="^(login|signup|verify|password_reset|licence_recovery)$",
    )

    @field_validator("otp")
    @classmethod
    def check_otp_format(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or len(v) != 6:
            raise ValueError("OTP must be exactly 6 digits")
        return v


class VerifyOTPResponse(BaseModel):
    """Response after OTP verification."""
    success: bool = True
    message: str
    verified: bool
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: Optional[int] = None
    user: Optional["UserResponse"] = None


# ───────────────────────────────────────────────
#  Password Schemas
# ───────────────────────────────────────────────
class ForgotPasswordRequest(BaseModel):
    """Request to initiate password reset."""
    email: EmailStr = Field(
        ...,
        description="Email address of the account",
    )


class ForgotPasswordResponse(BaseModel):
    """Response after password reset is initiated."""
    success: bool = True
    message: str
    otp_sent_to: str


class ResetPasswordRequest(BaseModel):
    """Request to reset password with OTP verification."""
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6, pattern="^[0-9]{6}$")
    new_password: str = Field(..., min_length=8)
    confirm_new_password: str

    @field_validator("new_password")
    @classmethod
    def check_new_password(cls, v: str) -> str:
        return validate_password_strength(v)

    @model_validator(mode="after")
    def passwords_match(self) -> "ResetPasswordRequest":
        if self.new_password != self.confirm_new_password:
            raise ValueError("Passwords do not match")
        return self


class ResetPasswordResponse(BaseModel):
    """Response after successful password reset."""
    success: bool = True
    message: str = "Password reset successfully. Please login with your new password."


class ChangePasswordRequest(BaseModel):
    """Request to change password (authenticated user)."""
    current_password: str
    new_password: str = Field(..., min_length=8)
    confirm_new_password: str

    @field_validator("new_password")
    @classmethod
    def check_new_password(cls, v: str) -> str:
        return validate_password_strength(v)

    @model_validator(mode="after")
    def passwords_match(self) -> "ChangePasswordRequest":
        if self.new_password != self.confirm_new_password:
            raise ValueError("New passwords do not match")
        return self


# ───────────────────────────────────────────────
#  Token Schemas
# ───────────────────────────────────────────────
class TokenRefreshRequest(BaseModel):
    """Request to refresh access token."""
    refresh_token: str = Field(..., description="Valid refresh token")


class TokenRefreshResponse(BaseModel):
    """Response with new access token."""
    success: bool = True
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    """Data encoded inside JWT token."""
    user_id: str
    username: str
    email: str
    tier: str
    is_admin: bool = False
    exp: Optional[datetime] = None


# ───────────────────────────────────────────────
#  User Response Schema
# ───────────────────────────────────────────────
class UserResponse(BaseModel):
    """Public user data returned in API responses."""
    id: str
    full_name: str
    username: str
    email: str
    mobile: Optional[str] = None
    avatar_url: Optional[str] = None
    tier: str
    is_admin: bool = False
    is_vip: bool = False
    projects_used: int
    projects_limit: int
    projects_remaining: int
    email_verified: bool
    mobile_verified: bool
    govt_id_verified: bool
    biometric_verified: bool
    verification_status: str
    is_seller: bool
    seller_verified: bool
    seller_rating: float
    total_apps_sold: int
    has_custom_voice: bool
    has_custom_character: bool
    character_name: Optional[str] = None
    revenue_sharing_agreed: bool
    status: str
    restriction_level: str
    created_at: datetime
    last_login: Optional[datetime] = None
    preferences: dict = {}

    model_config = {"from_attributes": True}

    @classmethod
    def from_db(cls, user) -> "UserResponse":
        """Create UserResponse from database User model."""
        return cls(
            id=user.id,
            full_name=user.full_name,
            username=user.username,
            email=user.email,
            mobile=user.mobile,
            avatar_url=user.avatar_url,
            tier=user.tier.value if hasattr(user.tier, 'value') else user.tier,
            is_admin=user.is_admin,
            is_vip=user.is_vip,
            projects_used=user.projects_used,
            projects_limit=user.projects_limit,
            projects_remaining=user.get_projects_remaining(),
            email_verified=user.email_verified,
            mobile_verified=user.mobile_verified,
            govt_id_verified=user.govt_id_verified,
            biometric_verified=user.biometric_verified,
            verification_status=user.verification_status.value
                if hasattr(user.verification_status, 'value')
                else user.verification_status,
            is_seller=user.is_seller,
            seller_verified=user.seller_verified,
            seller_rating=user.seller_rating,
            total_apps_sold=user.total_apps_sold,
            has_custom_voice=user.has_custom_voice,
            has_custom_character=user.has_custom_character,
            character_name=user.character_name,
            revenue_sharing_agreed=user.revenue_sharing_agreed,
            status=user.status.value if hasattr(user.status, 'value') else user.status,
            restriction_level=user.restriction_level.value
                if hasattr(user.restriction_level, 'value')
                else user.restriction_level,
            created_at=user.created_at,
            last_login=user.last_login,
            preferences=user.preferences or {},
        )


# ───────────────────────────────────────────────
#  Session Verification Schema
# ───────────────────────────────────────────────
class VerifySessionRequest(BaseModel):
    """Request to verify an existing session token."""
    token: str = Field(..., description="JWT access token to verify")


class VerifySessionResponse(BaseModel):
    """Response after session verification."""
    success: bool = True
    valid: bool
    user: Optional[UserResponse] = None
    message: Optional[str] = None


# ───────────────────────────────────────────────
#  Logout Schema
# ───────────────────────────────────────────────
class LogoutResponse(BaseModel):
    """Response after logout."""
    success: bool = True
    message: str = "Logged out successfully. See you next time! 🐯"


# ───────────────────────────────────────────────
#  Standard Error Response
# ───────────────────────────────────────────────
class ErrorResponse(BaseModel):
    """Standard error response format."""
    success: bool = False
    message: str
    error_code: Optional[str] = None
    details: Optional[dict] = None


# ── Resolve forward references ──
LoginResponse.model_rebuild()
VerifyOTPResponse.model_rebuild()
