"""Lightweight i18n: JSON catalogues, no gettext/babel toolchain.

Locale resolution order: explicit user setting -> `locale` cookie ->
Accept-Language header -> DEFAULT_LOCALE. Add a language by dropping
`app/locales/<code>.json` in place and listing it in AVAILABLE_LOCALES.

In templates:  {{ t("nav.account") }}   (falls back to the key if untranslated)
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import settings
from app.logging_config import logger

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
_catalogues: dict[str, dict[str, str]] = {}


def load_catalogues() -> None:
    _catalogues.clear()
    for code in settings.locale_list:
        path = LOCALES_DIR / f"{code}.json"
        if not path.exists():
            logger.warning("Locale file missing: %s", path)
            continue
        try:
            _catalogues[code] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error("Invalid locale file %s: %s", path, exc)


def available() -> list[str]:
    if not _catalogues:
        load_catalogues()
    return list(_catalogues.keys())


def translate(key: str, locale: str | None = None, **kwargs) -> str:
    if not _catalogues:
        load_catalogues()
    loc = locale or settings.DEFAULT_LOCALE
    text = (
        _catalogues.get(loc, {}).get(key)
        or _catalogues.get(settings.DEFAULT_LOCALE, {}).get(key)
        or key  # show the key so missing translations are obvious, never blank
    )
    return text.format(**kwargs) if kwargs else text


def resolve_locale(request, user=None) -> str:
    supported = available() or [settings.DEFAULT_LOCALE]

    if user is not None and getattr(user, "locale", None) in supported:
        return user.locale

    cookie = request.cookies.get("locale")
    if cookie in supported:
        return cookie

    header = request.headers.get("accept-language", "")
    for chunk in header.split(","):
        code = chunk.split(";")[0].strip().lower()
        if code in supported:
            return code
        base = code.split("-")[0]
        if base in supported:
            return base

    return settings.DEFAULT_LOCALE
