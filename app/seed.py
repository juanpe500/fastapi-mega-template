"""Idempotent seeding of the RBAC baseline (permissions + system roles).

Runs on startup so a fresh database is immediately usable. Safe to run repeatedly.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.logging_config import logger
from app.models.rbac import Permission, Role

# Fine-grained permissions used across the admin panel.
PERMISSIONS: dict[str, str] = {
    "users.manage": "Create, disable and edit users; assign roles",
    "roles.manage": "Create roles and edit their permissions",
    "billing.manage": "Manage plans, credits and refunds",
    "tickets.manage": "Reply to and manage support tickets",
    "errors.manage": "View and resolve server error logs",
    "settings.manage": "Edit app settings and feature flags",
    "users.impersonate": "Sign in as another user for support",
}

# System roles -> the permissions they hold. "admin" holds the "*" wildcard.
SYSTEM_ROLES: dict[str, dict] = {
    "admin": {"description": "Full access", "permissions": ["*"]},
    "user": {"description": "Standard account", "permissions": []},
    "support": {
        "description": "Support staff",
        "permissions": ["tickets.manage", "users.manage"],
    },
}


async def seed_rbac(db: AsyncSession) -> None:
    # Ensure the wildcard + all named permissions exist.
    wanted = {"*": "Wildcard: all permissions", **PERMISSIONS}
    existing = {
        p.name: p for p in (await db.execute(select(Permission))).scalars().all()
    }
    for name, desc in wanted.items():
        if name not in existing:
            perm = Permission(name=name, description=desc)
            db.add(perm)
            existing[name] = perm
    await db.flush()

    for role_name, spec in SYSTEM_ROLES.items():
        # Eager-load permissions so we never trigger an async lazy-load below.
        role = (
            await db.execute(
                select(Role).options(selectinload(Role.permissions)).where(Role.name == role_name)
            )
        ).scalar_one_or_none()
        wanted_perms = [existing[p] for p in spec["permissions"] if p in existing]
        if not role:
            # Assign permissions inline at creation (no lazy-load needed).
            db.add(Role(
                name=role_name,
                description=spec["description"],
                is_system=True,
                permissions=wanted_perms,
            ))
        else:
            # Add any missing grants without clobbering admin-made edits.
            current = role.permission_names
            for perm in wanted_perms:
                if perm.name not in current:
                    role.permissions.append(perm)


async def run_seed() -> None:
    async with SessionLocal() as db:
        await seed_rbac(db)
        await db.commit()
    logger.info("RBAC seed complete.")
