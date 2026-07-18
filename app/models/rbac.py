"""Real RBAC: Role <-> Permission (many-to-many) and User <-> Role (many-to-many).

A permission is a dotted string like "billing.manage" or "tickets.view". Roles
group permissions; users hold roles. Check access with require_permission(...)
or the require_role(...) shortcut (see app/security/deps.py).
"""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

# association tables
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        String(36),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "permissions"

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")

    roles: Mapped[list[Role]] = relationship(
        secondary=role_permissions, back_populates="permissions"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Permission {self.name}>"


class Role(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # System roles (admin/user) cannot be deleted from the admin UI.
    is_system: Mapped[bool] = mapped_column(default=False)

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions, back_populates="roles", lazy="selectin"
    )
    users: Mapped[list[User]] = relationship(  # noqa: F821
        secondary=user_roles, back_populates="roles"
    )

    @property
    def permission_names(self) -> set[str]:
        return {p.name for p in self.permissions}

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Role {self.name}>"
