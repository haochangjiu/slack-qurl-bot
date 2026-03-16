"""Client for file upload API (POST /api/upload)."""

import logging
from dataclasses import dataclass

import httpx

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class UploadResult:
    success: bool
    md5_hash: str | None
    resource_url: str | None
    qurl_link: str | None
    qurl_site: str | None
    expires_at: str | None
    error: str | None


async def upload_file(
    file_bytes: bytes,
    filename: str,
    content_type: str | None = None,
) -> UploadResult:
    """
    Upload file to the upload API.

    Args:
        file_bytes: Raw file content
        filename: Original filename
        content_type: MIME type (optional)

    Returns:
        UploadResult with qurl_link, resource_url, etc.
    """
    base = (settings.upload_api_url or "").rstrip("/")
    if not base:
        return UploadResult(
            success=False, md5_hash=None, resource_url=None,
            qurl_link=None, qurl_site=None, expires_at=None,
            error="Upload API not configured (UPLOAD_API_URL)"
        )

    url = f"{base}/api/upload"
    files = {"file": (filename, file_bytes, content_type or "application/octet-stream")}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, files=files)
            data = resp.json() if resp.content else {}

        if resp.status_code == 200 and data.get("success"):
            return UploadResult(
                success=True,
                md5_hash=data.get("md5_hash"),
                resource_url=data.get("resource_url"),
                qurl_link=data.get("qurl_link"),
                qurl_site=data.get("qurl_site"),
                expires_at=data.get("expires_at"),
                error=data.get("error"),
            )
        err = data.get("error", f"HTTP {resp.status_code}")
        return UploadResult(
            success=False, md5_hash=None, resource_url=None,
            qurl_link=None, qurl_site=None, expires_at=None,
            error=err,
        )
    except Exception as e:
        logger.error(f"Upload API error: {e}")
        return UploadResult(
            success=False, md5_hash=None, resource_url=None,
            qurl_link=None, qurl_site=None, expires_at=None,
            error=str(e),
        )
