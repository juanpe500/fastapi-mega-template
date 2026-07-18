"""Serves local-backend private files via signed, expiring links.

Only used when STORAGE_BACKEND=local. With the s3 backend, private files are
served by presigned S3 URLs and this route is never hit.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.config import settings
from app.services.storage import PRIVATE_DIR, LocalStorage, guess_type

router = APIRouter(tags=["files"])


@router.get("/files/{key:path}")
async def serve_private_file(key: str, token: str = ""):
    if settings.storage_is_s3:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not LocalStorage.verify_private_token(key, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired link")
    path = (PRIVATE_DIR / key).resolve()
    # Prevent path traversal outside the private dir.
    if PRIVATE_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type=guess_type(key))
