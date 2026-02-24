import json
import logging
from dataclasses import dataclass

import anthropic

from config import settings
from services.domain_resolver import domain_resolver

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """You are an intelligent assistant responsible for analyzing user messages and extracting structured information.

Your task is to extract the following information from user messages:
1. language - IMPORTANT: Detect the language of the user's message. Return "en" for English, "zh" for Chinese.
   - If the message is in English (e.g., "please give me", "I need", "help me"), return "en"
   - If the message is in Chinese (e.g., "请给我", "我需要", "帮我"), return "zh"
   - Default to "en" if uncertain
2. urls - List of URLs the user wants to access (MUST be complete URLs starting with https://)
3. wants_proxy - Whether the user needs a proxy/QURL link
4. expires_in - The validity period specified by the user (format like "1h", "24h", "7d", "1w")
5. reason - A brief description of the user's request (optional)

{custom_aliases}

URL Recognition Rules:
- IMPORTANT: First check if the mentioned name matches any custom internal domain alias above. If so, use that exact URL.
- If user mentions a website NAME (not a full URL), convert it to a complete URL:
  - "Amazon" or "亚马逊" → "https://amazon.com"
  - "Google" or "谷歌" → "https://google.com"
  - "GitHub" → "https://github.com"
  - "YouTube" or "油管" → "https://youtube.com"
  - "Twitter" or "X" or "推特" → "https://x.com"
  - "Facebook" or "脸书" → "https://facebook.com"
  - "Instagram" or "Ins" → "https://instagram.com"
  - "Netflix" or "奈飞" → "https://netflix.com"
  - "Reddit" → "https://reddit.com"
  - "LinkedIn" or "领英" → "https://linkedin.com"
  - "Baidu" or "百度" → "https://baidu.com"
  - "Taobao" or "淘宝" → "https://taobao.com"
  - "ChatGPT" or "OpenAI" → "https://chat.openai.com"
  - For other website names, use "https://{{name}}.com" format
- If user provides a partial URL like "amazon.com", convert to "https://amazon.com"
- If user provides a full URL, keep it as is
- Always return URLs with https:// prefix

Criteria for determining wants_proxy:
- User explicitly requests proxy, QURL, access link, secure link, etc.
- User asks how to access a website
- User mentions needing to bypass restrictions, VPN, etc.
- Chinese keywords: 代理, 访问, 链接, 打开, 连接, 翻墙, 科学上网, qurl
- English keywords: proxy, access, link, open, connect, vpn, qurl
- If the user only sends a URL/website name without explicitly requesting a proxy, wants_proxy should be false

Validity period recognition:
- "1小时" / "1 hour" → "1h"
- "24小时" / "24 hours" → "24h"
- "1天" / "1 day" → "1d"
- "7天" / "一周" / "7 days" / "1 week" → "7d"
- If not specified, return null

IMPORTANT: Always return results in JSON format without any other text.

Examples:
- Input: "please give me the QURL of Amazon" → {{"language": "en", "urls": ["https://amazon.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- Input: "帮我生成谷歌的代理链接" → {{"language": "zh", "urls": ["https://google.com"], "wants_proxy": true, "expires_in": null, "reason": null}}
- Input: "CRM proxy please, 7 days" → {{"language": "en", "urls": ["https://crm.mycompany.com"], "wants_proxy": true, "expires_in": "7d", "reason": null}}"""


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
            logger.debug(f"Claude response: {response_text}")

            # Parse JSON response
            data = json.loads(response_text)

            urls = data.get("urls", [])
            # Post-process to catch any custom domains AI might have missed
            urls = self._resolve_custom_domains(urls, text)

            return AnalysisResult(
                language=data.get("language", "en"),
                urls=urls,
                wants_proxy=data.get("wants_proxy", False),
                expires_in=data.get("expires_in"),
                reason=data.get("reason"),
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response: {e}")
            # Fallback to empty result with default language
            return AnalysisResult(
                language="en", urls=[], wants_proxy=False, expires_in=None, reason=None
            )
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            raise


# Singleton instance
ai_analyzer = AIAnalyzer()
