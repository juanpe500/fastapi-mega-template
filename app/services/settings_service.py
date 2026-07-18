"""DB-backed settings / feature flags, editable in the admin panel.

Use for values you want to change without a redeploy (toggles, limits, banners).
Secrets and infrastructure config belong in .env, not here.

    from app.services import settings_service
    if await settings_service.get(db, "signups_paused", False):
        ...
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import AppSetting

# Simple process-local cache; invalidated on write.
_cache: dict[str, Any] = {}


def _coerce(raw: str, value_type: str) -> Any:
    if value_type == "int":
        return int(raw or 0)
    if value_type == "float":
        return float(raw or 0)
    if value_type == "bool":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if value_type == "json":
        return json.loads(raw or "null")
    return raw


async def get(db: AsyncSession, key: str, default: Any = None) -> Any:
    if key in _cache:
        return _cache[key]
    row = (
        await db.execute(select(AppSetting).where(AppSetting.key == key))
    ).scalar_one_or_none()
    if row is None:
        return default
    value = _coerce(row.value, row.value_type)
    _cache[key] = value
    return value


async def set(  # noqa: A001 — deliberate, reads naturally at call sites
    db: AsyncSession,
    key: str,
    value: Any,
    *,
    value_type: str = "str",
    description: str = "",
) -> AppSetting:
    raw = json.dumps(value) if value_type == "json" else str(value)
    row = (
        await db.execute(select(AppSetting).where(AppSetting.key == key))
    ).scalar_one_or_none()
    if row is None:
        row = AppSetting(key=key)
        db.add(row)
    row.value = raw
    row.value_type = value_type
    if description:
        row.description = description
    await db.flush()
    _cache.pop(key, None)
    return row


async def all_settings(db: AsyncSession) -> list[AppSetting]:
    rows = await db.execute(select(AppSetting).order_by(AppSetting.key))
    return list(rows.scalars().all())


async def delete(db: AsyncSession, key: str) -> None:
    row = (
        await db.execute(select(AppSetting).where(AppSetting.key == key))
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
    _cache.pop(key, None)


def clear_cache() -> None:
    _cache.clear()
