# Backup & restore runbook

A backup you have never restored is not a backup. This is the drill — read it now,
not during an incident.

`scripts/backup_db.py` already creates the dumps and prunes old ones (see the cron
line below). This document is the **other half**: how to get the data *back*, and how
to prove the backups actually work.

## What is (and isn't) covered

| Data | Backed up by | Notes |
|---|---|---|
| Database (SQLite file / Postgres) | `scripts/backup_db.py` | The critical one — users, billing, everything |
| Uploaded files (avatars, attachments) | **your object store** | S3/R2 versioning + lifecycle, or `rsync` for local storage |
| `.env` / secrets | **you, manually** | Keep in a password manager / secrets vault, NOT in the DB backup |
| Redis | not backed up | It's a cache — treated as disposable |

## Take a backup

```bash
cd /srv/app
.venv/bin/python scripts/backup_db.py            # writes into BACKUP_DIR
```

Cron (already in the README):

```cron
0 2 * * *  cd /srv/app && .venv/bin/python scripts/backup_db.py >> logs/backup.log 2>&1
```

**Get a copy off the box.** A backup sitting on the same VPS dies with the VPS. Add
an offsite sync after the dump — e.g.:

```cron
30 2 * * *  rclone copy /srv/app/backups remote:myapp-backups --max-age 25h
```

## Restore — SQLite

Backups are plain SQLite files (online-backup copies, so they're consistent).

```bash
# 1. Stop the app so nothing writes mid-restore.
sudo systemctl stop myapp          # or: pkill gunicorn

# 2. Keep the current (broken) DB aside — never overwrite blind.
mv app.db app.db.broken-$(date +%F)

# 3. Put the chosen backup in place (filename is app-YYYYMMDD-HHMMSS.db).
cp backups/app-20260723-020000.db app.db

# 4. Bring migrations up to head (safe no-op if the dump is already current).
.venv/bin/alembic upgrade head

# 5. Start and verify.
sudo systemctl start myapp
curl -fsS http://127.0.0.1:8000/health
```

## Restore — Postgres

Backups are custom-format dumps (`-Fc`), restored with `pg_restore`.

```bash
sudo systemctl stop myapp

# Option A — restore into a FRESH database (safest; lets you compare before cutover).
createdb myapp_restore
pg_restore --no-owner --clean --if-exists -d myapp_restore backups/myapp-20260723-020000.dump
# point DATABASE_URL at myapp_restore, or rename databases once you've checked it.

# Option B — restore in place (destructive; only when you're sure).
pg_restore --no-owner --clean --if-exists -d "$DATABASE_URL" backups/myapp-20260723-020000.dump

.venv/bin/alembic upgrade head
sudo systemctl start myapp
curl -fsS http://127.0.0.1:8000/health
```

`pg_restore` must be the **same major version** as (or newer than) the server that
produced the dump. Mismatched versions are the #1 cause of a restore failing exactly
when you need it.

## Restore uploaded files

- **S3 / R2:** enable bucket **versioning** so an overwrite/delete is recoverable, and
  a lifecycle rule to expire noncurrent versions. Restore = copy the prior version back.
- **Local storage:** include the uploads directory in your offsite `rsync`/`rclone`,
  and restore it alongside the DB.

## Quarterly restore drill (put it on the calendar)

1. Spin up a throwaway box (or a local container).
2. Restore the **latest** backup there following the steps above.
3. Log in, open `/admin/dashboard`, load a user, confirm billing history renders.
4. Note **RTO** (how long the restore took) and **RPO** (age of the newest backup —
   i.e. how much data you'd have lost). If either is worse than you can accept, shorten
   the backup interval or automate the restore.
5. Tear the box down.

A drill that surfaces a broken/incomplete backup has done its job — fix it before it's
an emergency.

## GDPR note: erasure vs. backups

When a user is anonymised (`account_service.anonymize`), old backups still contain
their personal data for a while — that's expected and lawful. You do **not** have to
crack open every archive. Instead:

- Keep the retention window **short and documented** (e.g. "backups expire after 35
  days"), so erased data ages out on its own. `BACKUP_KEEP_DAYS` plus your offsite
  `--max-age` enforce this.
- If you ever restore an old backup, **re-run the purge job** afterwards
  (`purge_due_accounts`) so anyone erased before the snapshot is anonymised again.
