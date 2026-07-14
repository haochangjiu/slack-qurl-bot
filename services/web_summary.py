"""Fetch and summarize public web pages for the Slack bot."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import urllib.parse
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser

import httpx
from openai import AsyncOpenAI

from config import settings

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
}
_BLOCKED_HOST_SUFFIXES = (
    ".internal",
    ".local",
    ".localdomain",
)
_SUMMARY_SYSTEM_PROMPT = """You summarize webpage content for Slack users.

Return ONLY valid JSON in this shape:
{
  "title": "string",
  "summary": "string",
  "bullets": ["string", "string"],
  "warning": "string or null"
}

Rules:
- Use the requested language exactly: "zh" for Chinese, "en" for English.
- Keep the summary concise and factual, at most 3 sentences.
- Return 2 to 4 short bullet points.
- If the content looks sparse, blocked, or login-only, keep the output conservative and explain that in warning.
- Do not invent facts that are not supported by the provided page content.
"""


class WebSummaryError(Exception):
    """Raised when a web summary request cannot be completed."""

    def __init__(self, message_key: str, detail: str | None = None):
        super().__init__(detail or message_key)
        self.message_key = message_key
        self.detail = detail


@dataclass
class ExtractedPage:
    url: str
    title: str | None
    description: str | None
    text: str
    truncated: bool


@dataclass
class WebSummaryResult:
    url: str
    title: str
    summary: str
    bullets: list[str]
    warning: str | None
    truncated: bool


class _VisibleTextExtractor(HTMLParser):
    """Extract visible text while skipping obviously non-content tags."""

    _BLOCK_TAGS = {
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "section",
        "table",
        "tr",
        "ul",
    }
    _SKIP_TAGS = {
        "head",
        "noscript",
        "script",
        "style",
        "svg",
        "template",
        "title",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth == 0 and tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if self._skip_depth == 0 and tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str):
        if self._skip_depth > 0:
            return
        if data.strip():
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        text = unescape(text)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        return text.strip()


def normalize_summary_url(raw_url: str) -> str:
    """Normalize user-provided URL input for web fetching."""
    candidate = (raw_url or "").strip()
    if not candidate:
        raise WebSummaryError("summary_url_required")

    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES or not parsed.netloc:
        raise WebSummaryError("summary_invalid_url")

    normalized = parsed._replace(fragment="")
    return urllib.parse.urlunparse(normalized)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not ip.is_global


def _is_blocked_host(hostname: str) -> bool:
    host = (hostname or "").strip().rstrip(".").lower()
    if not host:
        return True
    if host in _BLOCKED_HOSTS:
        return True
    if any(host.endswith(suffix) for suffix in _BLOCKED_HOST_SUFFIXES):
        return True
    try:
        return _is_blocked_ip(ipaddress.ip_address(host))
    except ValueError:
        return False


def _extract_attr(tag: str, attr_name: str) -> str | None:
    pattern = rf"""\b{re.escape(attr_name)}\s*=\s*(["'])(.*?)\1"""
    match = re.search(pattern, tag, re.IGNORECASE | re.DOTALL)
    if match:
        return unescape(match.group(2).strip())
    return None


def _extract_meta_content(html_text: str, keys: set[str]) -> str | None:
    for match in re.finditer(r"<meta\b[^>]*>", html_text, re.IGNORECASE):
        tag = match.group(0)
        key = (_extract_attr(tag, "name") or _extract_attr(tag, "property") or "").strip().lower()
        if key in keys:
            content = _extract_attr(tag, "content")
            if content:
                return content
    return None


def _extract_title(html_text: str) -> str | None:
    og_title = _extract_meta_content(html_text, {"og:title", "twitter:title"})
    if og_title:
        return og_title

    match = re.search(r"<title\b[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None

    title = unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return title or None


class WebSummaryService:
    """Fetch, extract, and summarize a public web page."""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.atlascloud_api_key,
            base_url=settings.atlascloud_base_url,
        )
        self.model = settings.ai_model
        self.max_bytes = settings.web_summary_max_bytes
        self.max_chars = settings.web_summary_max_chars
        self.max_redirects = settings.web_summary_max_redirects
        self.timeout = httpx.Timeout(settings.web_summary_timeout_seconds)

    async def summarize_url(self, raw_url: str, lang: str = "en") -> WebSummaryResult:
        if not settings.web_summary_enabled:
            raise WebSummaryError("summary_disabled")

        url = normalize_summary_url(raw_url)
        page = await self._fetch_page(url)
        if not page.title and not page.description and not page.text:
            raise WebSummaryError("summary_no_content")

        source_text = self._build_source_text(page)
        if not source_text:
            raise WebSummaryError("summary_no_content")

        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=700,
                temperature=0,
                messages=[
                    {
                        "role": "system",
                        "content": _SUMMARY_SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Requested language: {lang}\n"
                            f"URL: {page.url}\n"
                            f"Title: {page.title or ''}\n"
                            f"Description: {page.description or ''}\n"
                            f"Content:\n{source_text}"
                        ),
                    }
                ],
            )
            response_text = completion.choices[0].message.content or ""
            data = self._extract_json(response_text)
            if data is None:
                logger.error("Failed to parse summary JSON: %s", response_text)
                raise WebSummaryError("summary_processing_error", "Invalid summary response")
        except WebSummaryError:
            raise
        except Exception as e:
            logger.error("Web summary generation failed: %s", e)
            raise WebSummaryError("summary_processing_error", str(e)) from e

        summary = self._normalize_summary_payload(data, page)
        if not summary.summary:
            raise WebSummaryError("summary_processing_error", "Empty summary response")
        return summary

    async def _fetch_page(self, url: str) -> ExtractedPage:
        headers = {
            "User-Agent": "Slack-QURL-Bot/summary",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        }

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            current_url = url
            for _ in range(self.max_redirects + 1):
                await self._validate_public_url(current_url)
                async with client.stream("GET", current_url, follow_redirects=False) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise WebSummaryError("summary_fetch_failed", "Redirect missing location")
                        current_url = urllib.parse.urljoin(str(response.url), location)
                        continue

                    if response.status_code >= 400:
                        raise WebSummaryError(
                            "summary_fetch_failed",
                            f"HTTP {response.status_code}",
                        )

                    content_type = (response.headers.get("content-type") or "").lower()
                    if content_type and not any(allowed in content_type for allowed in _ALLOWED_CONTENT_TYPES):
                        raise WebSummaryError("summary_non_html")

                    body, truncated = await self._read_limited_body(response)
                    final_url = str(response.url)
                    html_text = self._decode_body(body, content_type)

                return self._extract_page(final_url, html_text, truncated)

        raise WebSummaryError("summary_too_many_redirects")

    async def _validate_public_url(self, url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
            raise WebSummaryError("summary_invalid_url")
        if _is_blocked_host(host):
            raise WebSummaryError("summary_url_blocked")

        loop = asyncio.get_running_loop()
        port = parsed.port or (80 if parsed.scheme.lower() == "http" else 443)
        try:
            addr_info = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise WebSummaryError("summary_fetch_failed", f"DNS lookup failed: {e}") from e

        if not addr_info:
            raise WebSummaryError("summary_fetch_failed", "DNS lookup returned no records")

        for family, _, _, _, sockaddr in addr_info:
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if _is_blocked_ip(ip):
                raise WebSummaryError("summary_url_blocked")

    async def _read_limited_body(self, response: httpx.Response) -> tuple[bytes, bool]:
        content_length = response.headers.get("content-length")
        truncated = False
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    truncated = True
            except ValueError:
                pass

        chunks = bytearray()
        async for chunk in response.aiter_bytes():
            if len(chunks) + len(chunk) > self.max_bytes:
                remaining = self.max_bytes - len(chunks)
                if remaining > 0:
                    chunks.extend(chunk[:remaining])
                truncated = True
                break
            chunks.extend(chunk)
        return bytes(chunks), truncated

    def _decode_body(self, body: bytes, content_type: str) -> str:
        charset = "utf-8"
        match = re.search(r"charset=([a-zA-Z0-9._-]+)", content_type)
        if match:
            charset = match.group(1)
        try:
            return body.decode(charset, errors="replace")
        except LookupError:
            return body.decode("utf-8", errors="replace")

    def _extract_page(self, url: str, html_text: str, truncated: bool) -> ExtractedPage:
        title = _extract_title(html_text)
        description = _extract_meta_content(
            html_text,
            {"description", "og:description", "twitter:description"},
        )

        extractor = _VisibleTextExtractor()
        extractor.feed(html_text)
        text = extractor.get_text()
        text = text[: self.max_chars].strip()

        return ExtractedPage(
            url=url,
            title=title,
            description=description,
            text=text,
            truncated=truncated or len(text) >= self.max_chars,
        )

    def _build_source_text(self, page: ExtractedPage) -> str:
        parts = []
        if page.title:
            parts.append(f"Title: {page.title}")
        if page.description:
            parts.append(f"Description: {page.description}")
        if page.text:
            parts.append(page.text)
        return "\n\n".join(parts).strip()

    def _extract_json(self, text: str) -> dict | None:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None

        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    def _normalize_summary_payload(self, data: dict, page: ExtractedPage) -> WebSummaryResult:
        title = str(data.get("title") or page.title or page.url).strip()
        summary = str(data.get("summary") or "").strip()
        raw_bullets = data.get("bullets") or []
        bullets = [str(item).strip() for item in raw_bullets if str(item).strip()]
        bullets = bullets[:4]
        warning = data.get("warning")
        if warning is not None:
            warning = str(warning).strip() or None

        return WebSummaryResult(
            url=page.url,
            title=title,
            summary=summary,
            bullets=bullets,
            warning=warning,
            truncated=page.truncated,
        )


web_summary_service = WebSummaryService()
