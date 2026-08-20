<div align="center">

# FastAPI Mega-Template

<b>A batteries-included FastAPI starter so you never rebuild the boring 70% again.</b><br>
Distilled from many production apps — the best pattern from each.

<p>
  <a href="https://github.com/juanpe500/fastapi-mega-template/actions/workflows/ci.yml"><img src="https://github.com/juanpe500/fastapi-mega-template/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/FastAPI-async-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/SQLAlchemy-2.0_async-0891b2?style=flat-square" alt="SQLAlchemy 2.0">
  <img src="https://img.shields.io/badge/tests-22_passing-3fb950?style=flat-square" alt="22 tests">
  <img src="https://img.shields.io/badge/batteries-70+_features-7c8cff?style=flat-square" alt="70+ features">
</p>

<img src="assets/architecture.png" alt="FastAPI Mega-Template request lifecycle: client through security middleware, edge (CSP/CSRF, rate limit), APIRouter, auth (JWT/session/API key/2FA, RBAC), services (Stripe, storage, email) and data (SQLAlchemy, Redis)" width="100%">

</div>

Every request flows through the same clean spine: **security middleware → router → auth & RBAC →
service layer → data**, with Stripe, object storage, email, Redis and a background scheduler wired in
around it. The pieces above are real modules in `app/`, already connected and tested.

## What's included

- **App factory** (`create_app()`) + lifespan, clean `APIRouter` split (no monolith)
- **Config** — typed `pydantic-settings`, fully `.env`-driven
- **Async DB** (SQLAlchemy 2.0) — SQLite by default, Postgres by setting `DATABASE_URL`; optional read replica
- **Auth** — JWT (in an httpOnly cookie *and* `Authorization: Bearer`), **revocable server-side sessions**, refresh-token rotation, `X-API-Key`, **TOTP 2FA**, email verification + password reset
- **Real RBAC** — `Role` + `Permission` tables, `require_role(...)` / `require_permission(...)` dependencies, seeded `admin` / `user` / `support` roles
- **Admin panel** — server-rendered: dashboard, users (+credit adjust, role assign), roles/permissions editor, tickets queue, error log, plans/subscriptions
- **Stripe billing** — credits (one-time top-ups → ledger) **and** subscriptions (Checkout + Customer Portal), **idempotent** webhook (dedup table) handling checkout, subscription sync, refunds & disputes
- **Support tickets** — user ↔ staff threads
- **Ops** — rotating-file logging, DB-persisted **error log** viewer, rate limiting (proxy-aware, in-memory → Redis auto), **CSP + security headers**, custom 404/422/500 pages, health + readiness endpoints, optional Sentry & Telegram alerts
- **Static versioning** — `?v={{ deploy_version }}` + immutable cache headers
- **Legal pages** — Terms / Privacy / Refunds / Contact stubs
- **Templates** — `base.html` with `title/head/content/scripts` blocks, working forms, **zero CSS framework** (style it yourself)
- **Fernet crypto** helper for storing third-party API keys at rest (BYOK)

### Also included

- **Object storage** — one API over local disk or any S3-compatible backend (AWS S3, Cloudflare R2, MinIO, Backblaze). Public files can be served through your own CDN domain (`S3_PUBLIC_CDN_URL`, e.g. `cdn.mydomain.com`); private files use short-lived **presigned URLs** (locally: signed expiring links). Wired to **avatars** (public) and **ticket attachments** (private).
- **CSRF protection** — double-submit token on every form; header-auth (Bearer / API key) requests are exempt
- **2FA QR codes** — inline SVG (no external service) + **one-time recovery codes**
- **Background jobs** — APScheduler: session cleanup, expired-token purge, subscription dunning
- **Audit log** — logins, password/role/credit changes, impersonation; filterable at `/admin/audit`
- **Social login** — Google + GitHub OAuth (buttons appear when configured)
- **Bot protection** — Cloudflare Turnstile on register/login/forgot, auto-added to the CSP
- **Session management** — `/account/sessions` lists devices; revoke one or sign out everywhere
- **Admin impersonation** — "view as user" with a persistent banner and audit trail
- **Settings / feature flags** — DB-backed, editable at `/admin/settings`, no redeploy
- **Quality harness** — pytest suite, ruff, pre-commit, GitHub Actions CI, templated emails

### And also

- **Account lifecycle** — self-service **deactivate** (reversible by signing in again), **delete** with a 30-day grace period + scheduled purge, and a one-click **JSON data export** (GDPR)
- **Profile & email change** — edit display name/locale; changing email confirms the *new* address and notifies the *old* one, so a hijacked session can't silently move it
- **Notifications** — in-app centre + unread badge, per-kind email preferences, and one-click `/unsubscribe` (no login) for non-transactional kinds
- **Admin lists that scale** — pagination, sorting, filtering and **CSV export** on users / audit / errors / tickets / subscriptions, plus **bulk actions**
- **Receipts & tax** — customer billing profile (company, VAT ID, address), printable receipts, optional **Stripe Tax** (`automatic_tax` + `tax_id_collection`)
- **Security pack** — new-device **login alerts**, **HIBP** breached-password rejection (k-anonymity), **per-user** rate limits (not just per-IP), and **terms versioning** that forces re-acceptance
- **Ops** — admin-toggled **maintenance mode** (admins still get through), public `/status` page, Prometheus `/metrics`, and `scripts/backup_db.py` for cron
- **Cookie consent** — banner + analytics that only load *after* consent
- **i18n** — JSON catalogues in `app/locales/`, `{{ t("key") }}` in templates, `/locale/{code}` switcher
- **SEO** — OpenGraph/Twitter cards, canonical URLs, `robots.txt`, `sitemap.xml`
- **Soft delete** — tickets go to `/admin/tickets/trash` and can be restored
- **Referrals** — every user gets a share link (`/?ref=CODE`), attributed at signup with an optional credit bonus

---

<div align="center">

<img src="assets/pages.png" alt="The template's real login page running, unstyled — every route works out of the box behind 20 lines of CSS" width="100%">

</div>

Every page is **server-rendered and working** — the screenshot above is the real `/login`. The template
ships with a deliberately tiny **20-line stylesheet** so nothing fights your design: the markup, forms,
CSRF, flash messages and flows are done, and the look is entirely yours.

## Quick start

```bash
cp .env.example .env         # then set SECRET_KEY at minimum
python -m venv .venv && source .venv/bin/activate   # (Windows: .\.venv\Scripts\Activate.ps1)
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000. The **first account you register becomes admin**
(`FIRST_USER_IS_ADMIN=1`), so register, then visit `/admin`.

Helper launchers: `./run.sh` (Linux/macOS) or `./run.ps1` (Windows).

## Switching to Postgres

Set in `.env` (no code changes):

```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/mydb
```

Then `alembic upgrade head`. The `asyncpg` (app) and `psycopg` (Alembic) drivers
are already in `requirements.txt`.

## Enabling Redis (multi-worker rate limiting/caching)

```
REDIS_URL=redis://localhost:6379/0
```

Left blank, everything runs in-memory (fine for a single worker).

## Stripe

Set `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, then
create plans in `/admin/billing` (give each a Stripe **price id**). Point a
Stripe webhook at `POST /billing/webhook`. Credit packs use `kind=credit` with a
`credits_granted` amount; subscriptions use `kind=subscription` with an interval.

Local webhook testing:
```bash
stripe listen --forward-to localhost:8000/billing/webhook
```

## Object storage (S3 / R2 / MinIO)

Local disk is the default and needs no setup. To use a bucket:

```
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com   # omit for AWS S3
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_PUBLIC_BUCKET=my-public
S3_PRIVATE_BUCKET=my-private
S3_PUBLIC_CDN_URL=https://cdn.mydomain.com   # public files served from your domain
S3_FORCE_PATH_STYLE=1                        # MinIO / some R2 setups
```

Use it anywhere:

```python
from app.services.storage import get_storage
s = get_storage()
url = await s.save_public("avatars/x.png", data, "image/png")  # CDN URL if configured
await s.save_private("invoices/2026.pdf", pdf, "application/pdf")
link = await s.presigned_get("invoices/2026.pdf", expires=600)  # expiring link
upload_url = await s.presigned_put("uploads/big.zip", "application/zip")  # browser-direct (s3 only)
```

## Tests & linting

```bash
pip install -r requirements-dev.txt
pytest          # 22 tests covering auth, CSRF, 2FA, storage, tickets, billing, admin
ruff check .
pre-commit install
```

## Production

```bash
gunicorn -c gunicorn.conf.py app.main:app
```

Set `ENV=prod` (enables Secure cookies, disables `/docs`), `HSTS_ENABLED=1`
behind TLS, a strong `SECRET_KEY`, and run behind nginx/Cloudflare. If you run
more than one worker, set `REDIS_URL` so rate limits are shared and enable the
scheduler in **one** process only (`SCHEDULER_ENABLED=1` there, `0` elsewhere).

Backups — add to cron on the VPS:

```
0 2 * * *  cd /srv/app && .venv/bin/python scripts/backup_db.py >> logs/backup.log 2>&1
```

It uses SQLite's online-backup API or `pg_dump -Fc`, then prunes anything older
than `BACKUP_KEEP_DAYS`.

Maintenance mode is a DB flag — toggle it at `/admin/settings` (admins keep full
access, everyone else gets a 503 page). `/metrics` is Prometheus text format;
protect it with `METRICS_TOKEN` or block the path at your proxy.

## Layout

```
app/
  main.py            factory + lifespan            config.py     typed settings
  database.py        async engine + sessions       crypto.py     Fernet (BYOK)
  logging_config.py  rotating logs                 redis_client  optional redis
  errors.py          exception handlers            seed.py       RBAC seed
  scheduler.py       background jobs               templating.py Jinja env + render()
  ops.py             maintenance + metrics MW      pagination.py paging/sort/CSV
  i18n.py            JSON catalogues
  models/            base, rbac, user, billing, billing_profile, ticket,
                     errorlog, recovery, audit, oauth, setting, notification
  security/          passwords, tokens, deps, headers, ratelimit, csrf,
                     turnstile, breach_check
  services/          credit_service, stripe_service, email, storage, twofactor,
                     audit, settings_service, account_service, notifications,
                     referrals
  routers/           health, ops, auth, oauth, account, notifications, tickets,
                     pages, billing, files, admin/*
  templates/         base + auth/ account/ admin/ errors/ legal/ emails/ partials/
  locales/           en.json, es.json
  static/            css/app.css, js/app.js
migrations/          Alembic
scripts/             backup_db.py
tests/               pytest suite
```

## Security notes

- Change `SECRET_KEY` (and set `ENCRYPTION_KEY`) before production.
- The template ships **without** a hardcoded admin — the first registrant becomes
  admin. Lock this down (`FIRST_USER_IS_ADMIN=0` + `ADMIN_EMAILS=...`) once set up.
- Rate limits, CSP, and Secure cookies are on by default; tune them in `.env`.
