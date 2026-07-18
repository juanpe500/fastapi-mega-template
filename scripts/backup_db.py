"""Database backup — SQLite file copy or Postgres pg_dump, plus retention pruning.

    python scripts/backup_db.py                  # write into BACKUP_DIR
    python scripts/backup_db.py --out /mnt/vol   # somewhere else
    python scripts/backup_db.py --keep 14        # retention in days

Wire it into cron on the VPS:

    0 2 * * *  cd /srv/app && .venv/bin/python scripts/backup_db.py >> logs/backup.log 2>&1

Postgres needs `pg_dump` on PATH and its version to match the server's major
version. SQLite backups use the online-backup API, so they're safe to take while
the app is running.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def backup_sqlite(url: str, out_dir: Path) -> Path:
    # sqlite+aiosqlite:///./app.db -> ./app.db
    path = Path(url.split("///", 1)[1])
    if not path.exists():
        raise SystemExit(f"SQLite database not found: {path}")
    target = out_dir / f"{path.stem}-{_stamp()}.db"
    # Online backup: consistent even with the app mid-write.
    src = sqlite3.connect(str(path))
    dst = sqlite3.connect(str(target))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    return target


def backup_postgres(url: str, out_dir: Path) -> Path:
    if shutil.which("pg_dump") is None:
        raise SystemExit("pg_dump not found on PATH.")
    parsed = urlparse(url.replace("+asyncpg", "").replace("+psycopg", ""))
    name = (parsed.path.lstrip("/") or "db")
    target = out_dir / f"{name}-{_stamp()}.dump"
    # Custom format (-Fc) restores with pg_restore and compresses well.
    cmd = ["pg_dump", "--no-owner", "-Fc", "-f", str(target),
           url.replace("+asyncpg", "").replace("+psycopg", "")]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"pg_dump failed: {result.stderr.strip()}")
    return target


def prune(out_dir: Path, keep_days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=keep_days)
    removed = 0
    for f in out_dir.iterdir():
        if not f.is_file() or f.suffix not in {".db", ".dump"}:
            continue
        if datetime.fromtimestamp(f.stat().st_mtime, UTC) < cutoff:
            f.unlink()
            removed += 1
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up the application database.")
    parser.add_argument("--out", default=settings.BACKUP_DIR, help="output directory")
    parser.add_argument("--keep", type=int, default=settings.BACKUP_KEEP_DAYS,
                        help="delete backups older than this many days (0 = keep all)")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    url = settings.DATABASE_URL
    target = backup_sqlite(url, out_dir) if settings.is_sqlite else backup_postgres(url, out_dir)
    size_mb = target.stat().st_size / (1024 * 1024)
    print(f"[{_stamp()}] wrote {target} ({size_mb:.1f} MB)")

    if args.keep > 0:
        removed = prune(out_dir, args.keep)
        if removed:
            print(f"[{_stamp()}] pruned {removed} backup(s) older than {args.keep} days")


if __name__ == "__main__":
    main()
