"""Typed application settings, loaded from environment / .env.

Everything is env-driven so the same code runs on SQLite+in-memory for dev and
Postgres+Redis in production without edits. See .env.example for the full list.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    APP_NAME: str = "My App"
    ENV: str = "dev"  # dev | prod
    DEPLOY_VERSION: str = "1"
    BASE_URL: str = "http://localhost:8000"

    # --- Security ---
    SECRET_KEY: str = "change-me-dev-only"
    ENCRYPTION_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    SESSION_COOKIE_NAME: str = "session"
    SECURE_COOKIE: bool = False
    COOKIE_DOMAIN: str = ""

    # --- Database ---
    DATABASE_URL: str = "sqlite+aiosqlite:///./app.db"
    DATABASE_READ_URL: str = ""
    SQL_ECHO: bool = False

    # --- Redis ---
    REDIS_URL: str = ""

    # --- Rate limiting ---
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_MAX: int = 30
    RATE_LIMIT_WINDOW: int = 60

    # --- Security headers / CSP ---
    SECURITY_HEADERS_ENABLED: bool = True
    HSTS_ENABLED: bool = False
    CSP_EXTRA_SCRIPT_SRC: str = ""
    CSP_EXTRA_STYLE_SRC: str = ""
    CSP_EXTRA_CONNECT_SRC: str = ""
    CORS_ORIGINS: str = ""

    # --- Registration / accounts ---
    REGISTRATION_ENABLED: bool = True
    REQUIRE_EMAIL_VERIFICATION: bool = False
    FIRST_USER_IS_ADMIN: bool = True
    ADMIN_EMAILS: str = ""
    WELCOME_CREDITS: float = 0.0

    # --- Email ---
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_STARTTLS: bool = True
    EMAIL_FROM: str = "My App <no-reply@example.com>"
    # Shared secret your ESP quotes (?token=... or X-Webhook-Token) when POSTing
    # bounce/complaint events to /webhooks/email. Blank disables the endpoint.
    EMAIL_WEBHOOK_SECRET: str = ""

    # --- Stripe ---
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PORTAL_CONFIGURATION_ID: str = ""

    # --- Object storage (avatars, ticket attachments) ---
    STORAGE_BACKEND: str = "local"  # local | s3
    S3_ENDPOINT_URL: str = ""       # blank for AWS; set for R2/MinIO/Backblaze
    S3_REGION: str = "auto"
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_PUBLIC_BUCKET: str = ""
    S3_PRIVATE_BUCKET: str = ""
    S3_PUBLIC_CDN_URL: str = ""      # e.g. https://cdn.mydomain.com (serves the public bucket)
    S3_FORCE_PATH_STYLE: bool = False  # True for MinIO / some R2 setups
    UPLOAD_MAX_MB: int = 10

    # --- Bot protection (Cloudflare Turnstile) ---
    TURNSTILE_SITE_KEY: str = ""
    TURNSTILE_SECRET_KEY: str = ""

    # --- Social OAuth ---
    OAUTH_GOOGLE_CLIENT_ID: str = ""
    OAUTH_GOOGLE_CLIENT_SECRET: str = ""
    OAUTH_GITHUB_CLIENT_ID: str = ""
    OAUTH_GITHUB_CLIENT_SECRET: str = ""

    # --- Background scheduler ---
    SCHEDULER_ENABLED: bool = False
    SESSION_RETENTION_DAYS: int = 30

    # --- Account lifecycle ---
    # Days between "delete my account" and irreversible purge.
    ACCOUNT_DELETION_GRACE_DAYS: int = 30

    # --- Security hardening ---
    LOGIN_ALERTS_ENABLED: bool = True
    # Check new passwords against Have I Been Pwned (k-anonymity; no password sent).
    HIBP_ENABLED: bool = True
    # Bump to force everyone to re-accept the terms.
    TERMS_VERSION: str = "1"

    # --- Billing / tax ---
    STRIPE_TAX_ENABLED: bool = False
    INVOICE_COMPANY_NAME: str = ""
    INVOICE_COMPANY_ADDRESS: str = ""
    INVOICE_TAX_ID: str = ""

    # --- Ops ---
    METRICS_ENABLED: bool = True
    # Restrict /metrics to holders of this token (blank = open; put it behind your firewall).
    METRICS_TOKEN: str = ""
    # scripts/backup_db.py defaults
    BACKUP_DIR: str = "backups"
    BACKUP_KEEP_DAYS: int = 14

    # --- Analytics / consent ---
    # Injected only after the visitor accepts cookies. e.g. a Plausible/GA snippet URL.
    ANALYTICS_SCRIPT_URL: str = ""
    ANALYTICS_SITE_ID: str = ""
    COOKIE_BANNER_ENABLED: bool = True

    # --- PWA (installable web app) ---
    PWA_ENABLED: bool = True
    # short_name shows under the home-screen icon; keep it under ~12 chars.
    PWA_SHORT_NAME: str = ""
    PWA_THEME_COLOR: str = "#0d6efd"       # browser UI / status bar tint
    PWA_BACKGROUND_COLOR: str = "#ffffff"  # splash-screen background
    PWA_DISPLAY: str = "standalone"        # standalone | minimal-ui | browser

    # --- i18n ---
    DEFAULT_LOCALE: str = "en"
    # Comma-separated list of locales with files in app/locales/
    AVAILABLE_LOCALES: str = "en,es"

    # --- SEO ---
    SITE_DESCRIPTION: str = ""
    SITE_IMAGE: str = ""  # absolute URL for OpenGraph/Twitter cards

    # --- Referrals ---
    REFERRALS_ENABLED: bool = True
    # Credits granted to the referrer when someone they referred signs up.
    REFERRAL_BONUS_CREDITS: float = 0.0

    # --- Ops ---
    SENTRY_DSN: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"

    # ---------------------------------------------------------------- helpers
    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_prod(self) -> bool:
        return self.ENV.lower() in ("prod", "production")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cookie_secure(self) -> bool:
        # Always secure in prod; otherwise honour the explicit flag.
        return self.is_prod or self.SECURE_COOKIE

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def stripe_enabled(self) -> bool:
        return bool(self.STRIPE_SECRET_KEY)

    @property
    def redis_enabled(self) -> bool:
        return bool(self.REDIS_URL)

    @property
    def storage_is_s3(self) -> bool:
        return self.STORAGE_BACKEND.lower() == "s3"

    @property
    def turnstile_enabled(self) -> bool:
        return bool(self.TURNSTILE_SECRET_KEY and self.TURNSTILE_SITE_KEY)

    @property
    def oauth_providers(self) -> dict[str, bool]:
        return {
            "google": bool(self.OAUTH_GOOGLE_CLIENT_ID and self.OAUTH_GOOGLE_CLIENT_SECRET),
            "github": bool(self.OAUTH_GITHUB_CLIENT_ID and self.OAUTH_GITHUB_CLIENT_SECRET),
        }

    @property
    def any_oauth_enabled(self) -> bool:
        return any(self.oauth_providers.values())

    @property
    def locale_list(self) -> list[str]:
        return [loc.strip() for loc in self.AVAILABLE_LOCALES.split(",") if loc.strip()]

    @property
    def analytics_enabled(self) -> bool:
        return bool(self.ANALYTICS_SCRIPT_URL)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
