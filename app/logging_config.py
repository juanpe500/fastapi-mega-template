"""Centralised logging: rotating file handler + stderr, configured once.

Import `logger` anywhere:  from app.logging_config import logger
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import settings

_CONFIGURED = False


def setup_logging() -> logging.Logger:
    global _CONFIGURED
    log = logging.getLogger("app")
    if _CONFIGURED:
        return log

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    log.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # stderr
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    log.addHandler(stream)

    # rotating file (best-effort; never crash the app if the dir is read-only)
    try:
        log_dir = Path(settings.LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        fileh = RotatingFileHandler(
            log_dir / "app.log", maxBytes=5 * 1024 * 1024, backupCount=10, encoding="utf-8"
        )
        fileh.setFormatter(fmt)
        log.addHandler(fileh)
    except OSError as exc:  # pragma: no cover
        log.warning("File logging disabled: %s", exc)

    log.propagate = False
    _CONFIGURED = True
    return log


logger = setup_logging()
