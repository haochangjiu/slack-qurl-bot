"""Client for file upload API (POST /api/upload)."""

import json
import logging
import re
from dataclasses import dataclass

import httpx

from config import settings

logger = logging.getLogger(__name__)


def _extract_payload(data: dict) -> dict:
    """Support both flat and nested data structure. Returns the dict to read fields from."""
    if isinstance(data.get("data"), dict):
        return data["data"]
    return data


def _get(obj: dict, *keys: str) -> str | None:
    """Get first existing key value (supports snake_case and camelCase)."""
    for k in keys:
        v = obj.get(k)
        if v is not None and v != "":
            return str(v) if not isinstance(v, str) else v
    return None


def _parse_expires_at(obj: dict) -> str | None:
    """Parse expires_at from API. Supports expires_at, expiresAt, expiration, expires; also Unix timestamp."""
    from datetime import datetime, timezone

    raw = None
    for k in ("expires_at", "expiresAt", "expiration", "expires"):
        v = obj.get(k)
        if v is not None:
            raw = v
            break
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(raw), tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, OSError):
            return None
    return str(raw)


def extract_resource_id_from_url(url: str | None) -> str | None:
    """Extract resource_id from resource_url, e.g. .../resources/a173b247... -> a173b247..."""
    if not url:
        return None
    m = re.search(r"/resources/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None


@dataclass
class UploadResult:
    success: bool
    md5_hash: str | None
    resource_id: str | None  # e.g. rkrdrn7o79c, from API when available
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
            success=False, md5_hash=None, resource_id=None, resource_url=None,
            qurl_link=None, qurl_site=None, expires_at=None,
            error="Upload API not configured (UPLOAD_API_URL)"
        )

    url = f"{base}/api/upload"
    files = {"file": (filename, file_bytes, content_type or "application/octet-stream")}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, files=files)
            data = resp.json() if resp.content else {}

        if resp.status_code in (200, 201) and data.get("success"):
            payload = _extract_payload(data)
            resource_url = _get(payload, "resource_url", "resourceUrl")
            qurl_link = _get(payload, "qurl_link", "qurlLink")
            link = qurl_link or resource_url
            resource_id = _get(payload, "resource_id", "resourceId")
            if not resource_id and link:
                resource_id = extract_resource_id_from_url(link)
            return UploadResult(
                success=True,
                md5_hash=_get(payload, "md5_hash", "md5Hash"),
                resource_id=resource_id,
                resource_url=resource_url,
                qurl_link=qurl_link,
                qurl_site=_get(payload, "qurl_site", "qurlSite"),
                expires_at=_parse_expires_at(payload),
                error=data.get("error"),
            )
        err = data.get("error", f"HTTP {resp.status_code}")
        return UploadResult(
            success=False, md5_hash=None, resource_id=None, resource_url=None,
            qurl_link=None, qurl_site=None, expires_at=None,
            error=err,
        )
    except Exception as e:
        logger.error(f"Upload API error: {e}")
        return UploadResult(
            success=False, md5_hash=None, resource_id=None, resource_url=None,
            qurl_link=None, qurl_site=None, expires_at=None,
            error=str(e),
        )


async def upload_google_map(url: str) -> UploadResult:
    """
    Upload Google Map link as JSON to the upload API.

    Args:
        url: Google Maps URL (e.g. https://maps.app.goo.gl/V2F1h99QVgLEueA37)

    Returns:
        UploadResult with qurl_link, resource_url, etc.
    """
    base = (settings.upload_api_url or "").rstrip("/")
    if not base:
        return UploadResult(
            success=False, md5_hash=None, resource_id=None, resource_url=None,
            qurl_link=None, qurl_site=None, expires_at=None,
            error="Upload API not configured (UPLOAD_API_URL)"
        )

    upload_url = f"{base}/api/upload"
    payload = {
        "type": "google-map",
        "url": url,
    }
    files = {
        "file": (
            "google-map.json",
            json.dumps(payload).encode("utf-8"),
            "application/json",
        )
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(upload_url, files=files)
            data = resp.json() if resp.content else {}

        if resp.status_code in (200, 201) and data.get("success"):
            payload = _extract_payload(data)
            resource_url = _get(payload, "resource_url", "resourceUrl")
            qurl_link = _get(payload, "qurl_link", "qurlLink")
            link = qurl_link or resource_url
            resource_id = _get(payload, "resource_id", "resourceId")
            if not resource_id and link:
                resource_id = extract_resource_id_from_url(link)
            return UploadResult(
                success=True,
                md5_hash=_get(payload, "md5_hash", "md5Hash"),
                resource_id=resource_id,
                resource_url=resource_url,
                qurl_link=qurl_link,
                qurl_site=_get(payload, "qurl_site", "qurlSite"),
                expires_at=_parse_expires_at(payload),
                error=data.get("error"),
            )
        err = data.get("error", f"HTTP {resp.status_code}")
        return UploadResult(
            success=False, md5_hash=None, resource_id=None, resource_url=None,
            qurl_link=None, qurl_site=None, expires_at=None,
            error=err,
        )
    except Exception as e:
        logger.error(f"Upload Google Map API error: {e}")
        return UploadResult(
            success=False, md5_hash=None, resource_id=None, resource_url=None,
            qurl_link=None, qurl_site=None, expires_at=None,
            error=str(e),
        )
