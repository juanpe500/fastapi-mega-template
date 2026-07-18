"""Object storage abstraction: pluggable local-disk or S3-compatible backend.

Two access modes:
  * public  — anyone can read; returns a URL (rewritten to S3_PUBLIC_CDN_URL,
              e.g. https://cdn.mydomain.com, when configured).
  * private — access via short-lived presigned (S3) or signed (local) URLs.

Backends (STORAGE_BACKEND): "local" (default, zero-config) or "s3" (AWS S3,
Cloudflare R2, MinIO, Backblaze — anything speaking the S3 API).
"""
from __future__ import annotations

import asyncio
import mimetypes
from abc import ABC, abstractmethod
from pathlib import Path

from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import settings

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "static" / "uploads"
PRIVATE_DIR = Path(settings.LOG_DIR).resolve().parent / "private_uploads"

_signer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="storage-private")


def guess_type(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


class Storage(ABC):
    @abstractmethod
    async def save_public(self, key: str, data: bytes, content_type: str | None = None) -> str: ...

    @abstractmethod
    async def save_private(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> None: ...

    @abstractmethod
    def public_url(self, key: str) -> str: ...

    @abstractmethod
    async def presigned_get(self, key: str, expires: int = 3600) -> str: ...

    @abstractmethod
    async def presigned_put(self, key: str, content_type: str, expires: int = 3600) -> str: ...

    @abstractmethod
    async def delete(self, key: str, *, private: bool = False) -> None: ...


class LocalStorage(Storage):
    """Files on local disk. Public files are served by the /static mount; private
    files are streamed by the /files route after a signed, expiring link check."""

    def __init__(self) -> None:
        PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
        PRIVATE_DIR.mkdir(parents=True, exist_ok=True)

    def _write(self, base: Path, key: str, data: bytes) -> None:
        dest = base / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    async def save_public(self, key, data, content_type=None) -> str:
        await asyncio.to_thread(self._write, PUBLIC_DIR, key, data)
        return self.public_url(key)

    async def save_private(self, key, data, content_type=None) -> None:
        await asyncio.to_thread(self._write, PRIVATE_DIR, key, data)

    def public_url(self, key: str) -> str:
        return f"/static/uploads/{key}"

    async def presigned_get(self, key: str, expires: int = 3600) -> str:
        token = _signer.dumps({"key": key})
        return f"{settings.BASE_URL}/files/{key}?token={token}"

    async def presigned_put(self, key: str, content_type: str, expires: int = 3600) -> str:
        # Direct-to-storage uploads aren't meaningful on local disk; upload via the app.
        raise NotImplementedError("presigned_put requires the s3 backend")

    async def delete(self, key: str, *, private: bool = False) -> None:
        base = PRIVATE_DIR if private else PUBLIC_DIR
        await asyncio.to_thread(lambda: (base / key).unlink(missing_ok=True))

    @staticmethod
    def verify_private_token(key: str, token: str, max_age: int = 3600) -> bool:
        try:
            data = _signer.loads(token, max_age=max_age)
        except BadSignature:
            return False
        return data.get("key") == key


class S3Storage(Storage):
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        self._client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            config=Config(
                s3={"addressing_style": "path" if settings.S3_FORCE_PATH_STYLE else "auto"}
            ),
        )
        self.public_bucket = settings.S3_PUBLIC_BUCKET
        self.private_bucket = settings.S3_PRIVATE_BUCKET

    async def save_public(self, key, data, content_type=None) -> str:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.public_bucket,
            Key=key,
            Body=data,
            ContentType=content_type or guess_type(key),
        )
        return self.public_url(key)

    async def save_private(self, key, data, content_type=None) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.private_bucket,
            Key=key,
            Body=data,
            ContentType=content_type or guess_type(key),
        )

    def public_url(self, key: str) -> str:
        if settings.S3_PUBLIC_CDN_URL:
            return f"{settings.S3_PUBLIC_CDN_URL.rstrip('/')}/{key}"
        if settings.S3_ENDPOINT_URL:
            return f"{settings.S3_ENDPOINT_URL.rstrip('/')}/{self.public_bucket}/{key}"
        return f"https://{self.public_bucket}.s3.{settings.S3_REGION}.amazonaws.com/{key}"

    async def presigned_get(self, key: str, expires: int = 3600) -> str:
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.private_bucket, "Key": key},
            ExpiresIn=expires,
        )

    async def presigned_put(self, key: str, content_type: str, expires: int = 3600) -> str:
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "put_object",
            Params={"Bucket": self.private_bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires,
        )

    async def delete(self, key: str, *, private: bool = False) -> None:
        bucket = self.private_bucket if private else self.public_bucket
        await asyncio.to_thread(self._client.delete_object, Bucket=bucket, Key=key)


async def read_upload(upload, max_mb: int | None = None) -> bytes:
    """Read an UploadFile fully, enforcing a size cap. Raises ValueError if too big."""
    limit = (max_mb if max_mb is not None else settings.UPLOAD_MAX_MB) * 1024 * 1024
    data = await upload.read()
    if len(data) > limit:
        raise ValueError(f"File too large (max {max_mb or settings.UPLOAD_MAX_MB} MB)")
    return data


def safe_filename(name: str) -> str:
    keep = "-_.() "
    cleaned = "".join(c for c in (name or "file") if c.isalnum() or c in keep).strip()
    return cleaned[:120] or "file"


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = S3Storage() if settings.storage_is_s3 else LocalStorage()
    return _storage
