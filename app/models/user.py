"""User account + revocable server-side sessions."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.rbac import Role, user_roles


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(50), unique=True, index=True, default=None)
    password_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    display_name: Mapped[str] = mapped_column(String(120), default="")

    is_active: Mapped[bool] = mapped_column(default=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500), default=None)

    # Credits balance (money-like; use Numeric to avoid float drift).
    credits_balance: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))

    # API key (hashed) for programmatic access — see security/deps.get_api_user.
    api_key_hash: Mapped[str | None] = mapped_column(String(255), default=None, index=True)

    # TOTP 2FA
    totp_secret: Mapped[str | None] = mapped_column(String(64), default=None)
    totp_enabled: Mapped[bool] = mapped_column(default=False)

    # Email verification / password reset (short-lived tokens are hashed).
    verification_code: Mapped[str | None] = mapped_column(String(128), default=None)
    reset_token: Mapped[str | None] = mapped_column(String(128), default=None)
    reset_token_expires: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # Stripe linkage
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # --- account lifecycle ---
    # Self-deactivated: login reactivates. Distinct from an admin ban (is_active only).
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Set when the user requests deletion; purged by the scheduler after the grace period.
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )

    # --- pending email change (only applied once the NEW address is confirmed) ---
    pending_email: Mapped[str | None] = mapped_column(String(255), default=None)
    pending_email_token: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    pending_email_expires: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # --- compliance / prefs ---
    terms_version_accepted: Mapped[str | None] = mapped_column(String(20), default=None)
    locale: Mapped[str | None] = mapped_column(String(10), default=None)

    # --- referrals ---
    referral_code: Mapped[str | None] = mapped_column(
        String(20), unique=True, index=True, default=None
    )
    referred_by_id: Mapped[str | None] = mapped_column(String(36), index=True, default=None)

    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles, back_populates="users", lazy="selectin"
    )
    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    # --------------------------------------------------------------- helpers
    @property
    def role_names(self) -> set[str]:
        return {r.name for r in self.roles}

    @property
    def permissions(self) -> set[str]:
        perms: set[str] = set()
        for role in self.roles:
            perms |= role.permission_names
        return perms

    def has_role(self, name: str) -> bool:
        return name in self.role_names

    def has_permission(self, name: str) -> bool:
        # "*" is a wildcard super-permission (granted to the admin role).
        p = self.permissions
        return "*" in p or name in p

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.email}>"


class UserSession(UUIDMixin, TimestampMixin, Base):
    """A server-side session row referenced by `sid` inside the signed JWT.

    Lets us revoke individual sessions (logout / "sign out everywhere") even
    though the token itself is stateless.
    """

    __tablename__ = "user_sessions"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(400), default=None)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Set when an admin is impersonating this user; holds the admin's user id.
    impersonator_id: Mapped[str | None] = mapped_column(String(36), default=None)

    user: Mapped[User] = relationship(back_populates="sessions")
