import json
import logging
import re
from dataclasses import dataclass

import anthropic

from config import settings
from services.domain_resolver import domain_resolver

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """You are a URL extraction assistant for a QURL proxy bot. Users interact with this bot specifically to generate proxy links for websites. Your job is to extract structured information from user messages.

CONTEXT: This is a QURL proxy service bot. When users talk to this bot, they almost always want a proxy link generated. Default wants_proxy to true unless the user is clearly NOT asking for a proxy (e.g., asking a general question, saying hello, or asking for help/instructions).

Extract the following:
1. language - "en" for English, "zh" for Chinese. Default "en" if uncertain.
2. urls - List of URLs (MUST start with https://). Extract ALL websites mentioned.
3. wants_proxy - Whether user wants a proxy link. Default to TRUE if any website/URL is mentioned.
4. expires_in - Validity period if specified (format: "1h", "24h", "7d", "1w"). null if not specified.
5. reason - Brief description of the request (optional, can be null).

{custom_aliases}

URL Recognition Rules (VERY IMPORTANT - be aggressive about recognizing websites):
- First check custom internal domain aliases above.
- Website NAMES must be converted to URLs:
  - "Google" / "谷歌" → "https://google.com"
  - "Amazon" / "亚马逊" → "https://amazon.com"
  - "GitHub" → "https://github.com"
  - "YouTube" / "油管" → "https://youtube.com"
  - "Twitter" / "X" / "推特" → "https://x.com"
  - "Facebook" / "脸书" → "https://facebook.com"
  - "Instagram" / "Ins" → "https://instagram.com"
  - "Netflix" / "奈飞" → "https://netflix.com"
  - "Reddit" → "https://reddit.com"
  - "LinkedIn" / "领英" → "https://linkedin.com"
  - "Baidu" / "百度" → "https://baidu.com"
  - "Taobao" / "淘宝" → "https://taobao.com"
  - "ChatGPT" / "OpenAI" → "https://chat.openai.com"
  - "Wikipedia" / "维基百科" → "https://wikipedia.org"
  - "Spotify" → "https://spotify.com"
  - "TikTok" / "抖音国际版" → "https://tiktok.com"
  - ANY other recognizable website name → "https://{{name}}.com"
- Partial URLs like "google.com", "amazon.co.jp" → add "https://" prefix
- Full URLs → keep as-is
- ALWAYS return with https:// prefix

wants_proxy determination:
- RULE: This is a QURL proxy bot. If a user mentions ANY website, URL, domain, or website name → wants_proxy = true. ALWAYS.
- The ONLY case for wants_proxy = false is when the user sends a message with NO website/URL at all (e.g., greeting, asking for help, general question).
- Do NOT require explicit keywords like "proxy" or "代理". The user talking to this bot and mentioning a website IS the intent.

Validity period:
- "1小时" / "1 hour" → "1h"
- "24小时" / "24 hours" → "24h"  
- "1天" / "1 day" → "1d"
- "7天" / "一周" / "7 days" / "1 week" → "7d"
- If not specified → null

CRITICAL: Return ONLY a valid JSON object. No markdown, no explanation, no extra text.

Examples with different websites, languages, and phrasings:
- "pls create a qurl for Google" → {{"language": "en", "urls": ["https://google.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "google.com I need a proxy" → {{"language": "en", "urls": ["https://google.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "I want to access YouTube" → {{"language": "en", "urls": ["https://youtube.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "generate a link for github.com" → {{"language": "en", "urls": ["https://github.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "need Amazon proxy" → {{"language": "en", "urls": ["https://amazon.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "give me Netflix access" → {{"language": "en", "urls": ["https://netflix.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "reddit.com" → {{"language": "en", "urls": ["https://reddit.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "Twitter" → {{"language": "en", "urls": ["https://x.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "https://example.com/path?q=1" → {{"language": "en", "urls": ["https://example.com/path?q=1"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "帮我访问谷歌" → {{"language": "zh", "urls": ["https://google.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "我需要YouTube的代理" → {{"language": "zh", "urls": ["https://youtube.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "给我一个Amazon的代理" → {{"language": "zh", "urls": ["https://amazon.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "要github代理" → {{"language": "zh", "urls": ["https://github.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "我要某个网站的代理 amazon.com" → {{"language": "zh", "urls": ["https://amazon.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "打开Netflix" → {{"language": "zh", "urls": ["https://netflix.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- "CRM proxy please, 7 days" → {{"language": "en", "urls": ["https://crm.mycompany.com"], "wants_proxy": true, "expires_in": "7d", "reason": null}}
- "hello" → {{"language": "en", "urls": [], "wants_proxy": false, "expires_in": null, "reason": null}}
- "怎么用这个机器人" → {{"language": "zh", "urls": [], "wants_proxy": false, "expires_in": null, "reason": null}}"""


@dataclass
class AnalysisResult:
    language: str
    urls: list[str]
    wants_proxy: bool
    expires_in: str | None
    reason: str | None


class AIAnalyzer:
    """Use Claude to analyze user messages."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def _get_system_prompt(self) -> str:
        """Build system prompt with custom domain aliases."""
        custom_aliases = domain_resolver.get_aliases_prompt()
        return SYSTEM_PROMPT_TEMPLATE.format(custom_aliases=custom_aliases)

    def _resolve_custom_domains(self, urls: list[str], text: str) -> list[str]:
        """
        Post-process URLs to resolve any custom domain aliases that AI might have missed.

        Args:
            urls: List of URLs from AI analysis
            text: Original user message

        Returns:
            Updated list of URLs with custom domains resolved
        """
        resolved_urls = []

        for url in urls:
            resolved_urls.append(url)

        # Also check if any word in the text matches a custom alias
        words = text.replace(",", " ").replace(".", " ").split()
        for word in words:
            resolved = domain_resolver.resolve(word)
            if resolved and resolved not in resolved_urls:
                # Check if this alias wasn't already captured
                resolved_urls.append(resolved)

        return resolved_urls

    def _extract_json(self, text: str) -> dict | None:
        """
        Extract JSON object from text that may contain extra content
        (e.g. markdown fences, explanatory text before/after JSON).
        """
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object within the text
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None

    async def analyze(self, text: str) -> AnalysisResult:
        """
        Analyze user message to extract intent, URLs, and language.

        Args:
            text: User message text

        Returns:
            AnalysisResult with extracted information including language
        """
        try:
            system_prompt = self._get_system_prompt()

            message = self.client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=500,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": f"Analyze the following user message:\n\n{text}",
                    }
                ],
            )

            response_text = message.content[0].text
            logger.info(f"Claude raw response: {response_text}")

            data = self._extract_json(response_text)
            if data is None:
                logger.error(f"Failed to extract JSON from Claude response: {response_text}")
                return AnalysisResult(
                    language="en", urls=[], wants_proxy=False, expires_in=None, reason=None
                )

            urls = data.get("urls", [])
            urls = self._resolve_custom_domains(urls, text)

            wants_proxy = data.get("wants_proxy", True)
            if "qurl" in text.lower():
                wants_proxy = True

            return AnalysisResult(
                language=data.get("language", "en"),
                urls=urls,
                wants_proxy=wants_proxy,
                expires_in=data.get("expires_in"),
                reason=data.get("reason"),
            )

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            raise


# Singleton instance
ai_analyzer = AIAnalyzer()
