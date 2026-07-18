# ═══════════════════════════════════════════════════════════════
#  VengaiCode — User Database Model
#  models/user.py — SQLAlchemy ORM model for users
# ═══════════════════════════════════════════════════════════════

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import List, Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, String, Text, JSON, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, Mapped
from sqlalchemy.sql import func

from app.core.database import Base


# ───────────────────────────────────────────────
#  Enums
# ───────────────────────────────────────────────
class UserTier(str, PyEnum):
    FREE = "free"
    CREATOR = "creator"
    PROFESSIONAL = "professional"
    STUDIO = "studio"
    WL_BASIC = "wl_basic"
    WL_PRO = "wl_pro"
    WL_FULL = "wl_full"


class UserStatus(str, PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BANNED = "banned"
    PENDING_VERIFICATION = "pending_verification"
    WARNED = "warned"


class VerificationStatus(str, PyEnum):
    NOT_STARTED = "not_started"
    EMAIL_VERIFIED = "email_verified"
    MOBILE_VERIFIED = "mobile_verified"
    GOVT_ID_VERIFIED = "govt_id_verified"
    BIOMETRIC_VERIFIED = "biometric_verified"
    FULLY_VERIFIED = "fully_verified"


class RestrictionLevel(str, PyEnum):
    NONE = "none"
    WARNING = "warning"
    FEATURE_LOCK = "feature_lock"
    PROJECT_FREEZE = "project_freeze"
    MARKETPLACE_BAN = "marketplace_ban"
    SELLING_SUSPENSION = "selling_suspension"
    ACCOUNT_SUSPENDED = "account_suspended"
    PERMANENT_BAN = "permanent_ban"


# ───────────────────────────────────────────────
#  User Model
# ───────────────────────────────────────────────
class User(Base):
    """
    VengaiCode user account.
    Stored in PostgreSQL (Supabase) — marketplace & account data.
    Local user preferences stored in SQLite on user's machine.
    """
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("mobile", name="uq_users_mobile"),
        Index("ix_users_email", "email"),
        Index("ix_users_username", "username"),
        Index("ix_users_status", "status"),
        Index("ix_users_tier", "tier"),
        Index("ix_users_created_at", "created_at"),
    )

    # ── Primary Key ──
    id: str = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )

    # ── Basic Info ──
    full_name: str = Column(String(255), nullable=False)
    # NOTE: index=True intentionally removed from username/email below —
    # they already have explicit Index() entries in __table_args__ above.
    # Keeping both caused "index already exists" errors on SQLite, since
    # SQLAlchemy would try to create the same-named index twice.
    username: str = Column(String(50), nullable=False)
    email: str = Column(String(255), nullable=False)
    mobile: Optional[str] = Column(String(20), nullable=True)
    avatar_url: Optional[str] = Column(String(500), nullable=True)
    bio: Optional[str] = Column(Text, nullable=True)

    # ── Authentication ──
    hashed_password: str = Column(String(255), nullable=False)
    is_active: bool = Column(Boolean, default=True, nullable=False)
    last_login: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    last_login_ip: Optional[str] = Column(String(45), nullable=True)
    failed_login_attempts: int = Column(Integer, default=0, nullable=False)
    lockout_until: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)

    # ── Subscription & Tier ──
    tier: UserTier = Column(
        Enum(UserTier),
        default=UserTier.FREE,
        nullable=False,
    )
    tier_expires_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    projects_used: int = Column(Integer, default=0, nullable=False)
    projects_limit: int = Column(Integer, default=1, nullable=False)
    # -1 = unlimited (Studio tier)

    # ── Admin Controls ──
    # Admin can extend free tier to any user 🐯
    is_free_extended: bool = Column(Boolean, default=False, nullable=False)
    free_extended_until: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    free_extended_by: Optional[str] = Column(String(36), nullable=True)
    # Admin user ID who extended
    free_extended_reason: Optional[str] = Column(Text, nullable=True)

    # VIP status — special treatment throughout platform
    is_vip: bool = Column(Boolean, default=False, nullable=False)
    vip_granted_by: Optional[str] = Column(String(36), nullable=True)
    vip_granted_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)

    # Admin restriction controls
    status: UserStatus = Column(
        Enum(UserStatus),
        default=UserStatus.ACTIVE,
        nullable=False,
    )
    restriction_level: RestrictionLevel = Column(
        Enum(RestrictionLevel),
        default=RestrictionLevel.NONE,
        nullable=False,
    )
    restriction_reason: Optional[str] = Column(Text, nullable=True)
    restriction_expires_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    restricted_by: Optional[str] = Column(String(36), nullable=True)
    restriction_count: int = Column(Integer, default=0, nullable=False)

    # ── Identity Verification ──
    verification_status: VerificationStatus = Column(
        Enum(VerificationStatus),
        default=VerificationStatus.NOT_STARTED,
        nullable=False,
    )
    email_verified: bool = Column(Boolean, default=False, nullable=False)
    email_verified_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    mobile_verified: bool = Column(Boolean, default=False, nullable=False)
    mobile_verified_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    govt_id_verified: bool = Column(Boolean, default=False, nullable=False)
    govt_id_verified_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    govt_id_type: Optional[str] = Column(String(50), nullable=True)
    # "aadhaar", "pan", "passport"
    biometric_verified: bool = Column(Boolean, default=False, nullable=False)
    biometric_verified_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    biometric_type: Optional[str] = Column(String(50), nullable=True)
    # "fingerprint", "face", "both"

    # ── Seller Profile (Marketplace) ──
    is_seller: bool = Column(Boolean, default=False, nullable=False)
    seller_verified: bool = Column(Boolean, default=False, nullable=False)
    seller_rating: float = Column(Float, default=0.0, nullable=False)
    seller_review_count: int = Column(Integer, default=0, nullable=False)
    total_apps_sold: int = Column(Integer, default=0, nullable=False)
    total_revenue_earned: float = Column(Float, default=0.0, nullable=False)
    show_revenue_publicly: bool = Column(Boolean, default=False, nullable=False)
    response_rate: float = Column(Float, default=0.0, nullable=False)
    # % of messages responded to within 48 hours
    completion_rate: float = Column(Float, default=0.0, nullable=False)
    # % of custom orders completed successfully

    # Seller social links
    github_url: Optional[str] = Column(String(500), nullable=True)
    linkedin_url: Optional[str] = Column(String(500), nullable=True)
    website_url: Optional[str] = Column(String(500), nullable=True)
    twitter_url: Optional[str] = Column(String(500), nullable=True)

    # ── Personal Branding ──
    has_custom_voice: bool = Column(Boolean, default=False, nullable=False)
    has_custom_character: bool = Column(Boolean, default=False, nullable=False)
    character_style: Optional[str] = Column(String(50), nullable=True)
    # "realistic", "cartoon", "anime", "pixel", "3d"
    character_name: Optional[str] = Column(String(100), nullable=True)

    # ── Payment & Commission ──
    razorpay_contact_id: Optional[str] = Column(String(100), nullable=True)
    razorpay_fund_account_id: Optional[str] = Column(String(100), nullable=True)
    bank_account_verified: bool = Column(Boolean, default=False, nullable=False)
    total_commission_paid: float = Column(Float, default=0.0, nullable=False)

    # Revenue sharing agreement signed
    revenue_sharing_agreed: bool = Column(Boolean, default=False, nullable=False)
    revenue_sharing_agreed_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    revenue_sharing_version: Optional[str] = Column(String(20), nullable=True)
    # Version of agreement they signed

    # ── Preferences (stored as JSON for flexibility) ──
    preferences: dict = Column(JSON, default=dict, nullable=False)
    # {
    #   "theme": "dark",
    #   "language": "en",
    #   "notifications": { "email": true, "sms": true, "push": true },
    #   "audio": { "language": "ta", "accent": "indian", "voice": "female" }
    # }

    # ── Metadata ──
    created_at: datetime = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: datetime = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    # Soft delete

    # ── Relationships ──
    projects = relationship(
        "Project",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    marketplace_apps = relationship(
        "MarketplaceApp",
        back_populates="seller",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    """licences = relationship(
        "Licence",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    transactions = relationship(
        "Transaction",
        back_populates="user",
        lazy="dynamic",
    )
    notifications = relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )"""

    # ── Helper Methods ──
    def can_create_project(self) -> bool:
        """Check if user can create a new project based on tier limits."""
        if self.projects_limit == -1:
            return True  # Unlimited
        if self.is_free_extended:
            return True  # Admin extended their free tier
        return self.projects_used < self.projects_limit

    def is_fully_verified(self) -> bool:
        """Check if user has completed all verification layers."""
        return (
            self.email_verified
            and self.mobile_verified
            and self.govt_id_verified
            and self.biometric_verified
        )

    def is_restricted(self) -> bool:
        """Check if user account has any restriction."""
        return self.restriction_level != RestrictionLevel.NONE

    def can_sell(self) -> bool:
        """Check if user is allowed to sell on marketplace."""
        if self.restriction_level in [
            RestrictionLevel.MARKETPLACE_BAN,
            RestrictionLevel.SELLING_SUSPENSION,
            RestrictionLevel.ACCOUNT_SUSPENDED,
            RestrictionLevel.PERMANENT_BAN,
        ]:
            return False
        return self.is_seller and self.seller_verified and self.revenue_sharing_agreed

    def get_projects_remaining(self) -> int:
        """Get number of projects user can still create."""
        if self.projects_limit == -1:
            return 999999  # Effectively unlimited
        return max(0, self.projects_limit - self.projects_used)

    def __repr__(self) -> str:
        return (
            f"<User id={self.id[:8]}... username={self.username} "
            f"tier={self.tier} status={self.status}>"
        )


# ───────────────────────────────────────────────
#  OTP Model — Temporary OTP Storage
# ───────────────────────────────────────────────
class OTPRecord(Base):
    """
    Temporary OTP records for email/mobile verification.
    Auto-expired after MSG91_OTP_EXPIRE_MINUTES.
    """
    __tablename__ = "otp_records"
    __table_args__ = (
        Index("ix_otp_target_type", "target", "otp_type"),
        Index("ix_otp_expires_at", "expires_at"),
    )

    id: str = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    target: str = Column(String(255), nullable=False)
    # Email address or mobile number
    otp_type: str = Column(String(20), nullable=False)
    # "email" or "mobile"
    otp_hash: str = Column(String(255), nullable=False)
    # Hashed OTP — never store plain OTP
    purpose: str = Column(String(50), nullable=False)
    # "login", "signup", "verify", "password_reset", "licence_recovery"
    attempts: int = Column(Integer, default=0, nullable=False)
    max_attempts: int = Column(Integer, default=3, nullable=False)
    is_used: bool = Column(Boolean, default=False, nullable=False)
    expires_at: datetime = Column(DateTime(timezone=True), nullable=False)
    created_at: datetime = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    used_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    user_id: Optional[str] = Column(String(36), ForeignKey("users.id"), nullable=True)

    def is_expired(self) -> bool:
        from datetime import timezone
        expires = self.expires_at
        if expires.tzinfo is None:
            # SQLite stores timezone-naive datetimes — treat as UTC
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires

    def is_exhausted(self) -> bool:
        return self.attempts >= self.max_attempts

    def __repr__(self) -> str:
        return (
            f"<OTPRecord target={self.target[:10]}... "
            f"type={self.otp_type} purpose={self.purpose}>"
        )


# ───────────────────────────────────────────────
#  Admin Action Log
# ───────────────────────────────────────────────
class AdminAction(Base):
    """
    Audit log for all admin actions — extend free, restrict, ban, etc.
    Every admin action is permanently logged — accountability and transparency.
    """
    __tablename__ = "admin_actions"
    __table_args__ = (
        Index("ix_admin_actions_target_user", "target_user_id"),
        Index("ix_admin_actions_action_type", "action_type"),
        Index("ix_admin_actions_created_at", "created_at"),
    )

    id: str = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    admin_id: str = Column(String(36), nullable=False)
    target_user_id: str = Column(
        String(36),
        ForeignKey("users.id"),
        nullable=False,        
    )
    action_type: str = Column(String(100), nullable=False)
    # "extend_free", "restrict", "ban", "warn", "upgrade_tier",
    # "vip_grant", "vip_revoke", "suspend", "unsuspend"
    action_details: dict = Column(JSON, default=dict, nullable=False)
    # Full details of what was changed
    reason: str = Column(Text, nullable=False)
    # Admin MUST provide reason for every action
    previous_state: dict = Column(JSON, default=dict, nullable=False)
    # Snapshot of user state before action — for audit trail
    new_state: dict = Column(JSON, default=dict, nullable=False)
    # Snapshot of user state after action
    created_at: datetime = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    ip_address: Optional[str] = Column(String(45), nullable=True)
    # IP address of admin who performed action

    def __repr__(self) -> str:
        return (
            f"<AdminAction admin={self.admin_id[:8]}... "
            f"target={self.target_user_id[:8]}... action={self.action_type}>"
        )
