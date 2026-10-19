"""Public Content Credentials check (M7.1).

``POST /api/v1/legal/content-credentials`` takes one MP4 (multipart field
``file``) and answers whether it carries a C2PA manifest, who signed it,
whether the signature is valid, whether the signer is on the reader's trust
list, and whether the manifest marks it as AI-generated (and made with
Menivor, with its content id for a takedown report).

No account is needed; the call is rate-limited per caller. The upload is
streamed to a temporary file, read, and deleted in the same request. Nothing is
stored.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from fastapi import File, Request, UploadFile

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.services.compose import provenance as content_credentials
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

CHECK_RATE_LIMIT = 20
CHECK_RATE_WINDOW_S = 3600
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
ALLOWED_TYPES = {"video/mp4": "video/mp4", "video/quicktime": "video/mp4", "application/octet-stream": "video/mp4"}


def _spool(upload: UploadFile, request_id: str) -> str:
    fd, path = tempfile.mkstemp(prefix="c2pa-check-", suffix=".mp4")
    written = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = upload.file.read(CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HttpException(
                        task_id=request_id, status_code=413,
                        message=f"the video is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
                    )
                out.write(chunk)
    except BaseException:
        os.remove(path)
        raise
    if written == 0:
        os.remove(path)
        raise HttpException(task_id=request_id, status_code=400, message="the file is empty")
    return path


def _verdict(summary: dict[str, Any]) -> str:
    if not summary.get("present"):
        return "No Content Credentials found in this file."
    if not summary.get("valid"):
        return "Content Credentials were found, but the signature does not check out (the file was changed after signing)."
    who = "Menivor" if summary.get("made_with_menivor") else (summary.get("signer") or "an unknown signer")
    ai = " and marked as AI-generated" if summary.get("ai_generated") else ""
    if not summary.get("trusted"):
        # The signer name and the "made with Menivor" claim are written by
        # whoever signed the file; without a trust-list signer anyone can
        # write them into their own manifest, so never confirm the maker.
        return (
            f"Says it was signed by {who}{ai}. The signature matches the file, but the signer "
            "is not on a C2PA trust list, so who made it cannot be confirmed."
        )
    return f"Signed by {who}{ai}. The signature is valid."


@router.post(
    "/legal/content-credentials",
    tags=["Legal"],
    summary="Check a video for C2PA Content Credentials",
    responses={
        400: {"description": "The file is empty or not an MP4"},
        413: {"description": "The file is too large"},
        429: {"description": "Too many checks from this caller"},
    },
)
def check_content_credentials(request: Request, file: UploadFile = File(...)) -> Any:
    request_id = base.get_task_id(request)
    enforce_rate_limit(request, "legal:c2pa-check", CHECK_RATE_LIMIT, CHECK_RATE_WINDOW_S)
    mime = ALLOWED_TYPES.get((file.content_type or "application/octet-stream").lower())
    if mime is None:
        raise HttpException(task_id=request_id, status_code=400, message="upload an MP4 video")
    path = _spool(file, request_id)
    try:
        summary = content_credentials.read_manifest(path, mime)
    except content_credentials.ContentCredentialsError:
        raise HttpException(task_id=request_id, status_code=400, message="this file could not be read as an MP4 video")
    finally:
        os.remove(path)
    return utils.get_response(200, {**summary, "verdict": _verdict(summary)})


__all__ = ["router", "check_content_credentials"]
