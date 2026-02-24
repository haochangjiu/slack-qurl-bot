import re
from urllib.parse import urlparse


def extract_urls(text: str) -> list[str]:
    """Extract URLs from text message."""
    urls = []

    # First, extract Slack formatted links: <http://example.com|display_text> or <http://example.com>
    slack_link_pattern = r'<(https?://[^|>]+)(?:\|[^>]+)?>'
    for match in re.finditer(slack_link_pattern, text):
        urls.append(match.group(1))

    # Remove Slack links from text to avoid duplicate matching
    clean_text = re.sub(slack_link_pattern, ' ', text)

    # Pattern to match URLs (with or without protocol)
    url_pattern = r'https?://[^\s<>"\']+'
    domain_pattern = r'(?<!\S)([a-zA-Z0-9][-a-zA-Z0-9]*\.)+[a-zA-Z]{2,}(?:/[^\s<>"\']*)?(?!\S)'

    # Find full URLs with protocol
    for match in re.finditer(url_pattern, clean_text):
        url = match.group()
        if url not in urls:
            urls.append(url)

    # Find domain-only patterns (like google.com)
    for match in re.finditer(domain_pattern, clean_text):
        domain = match.group().strip()
        if domain and not any(domain in url for url in urls):
            urls.append(f"https://{domain}")

    return urls


def normalize_url(url: str) -> str:
    """Normalize URL to ensure it has https:// prefix."""
    url = url.strip()
    # Convert http:// to https://
    if url.startswith("http://"):
        url = "https://" + url[7:]
    elif not url.startswith("https://"):
        url = f"https://{url}"
    return url


def is_valid_url(url: str) -> bool:
    """Check if URL is valid."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False
