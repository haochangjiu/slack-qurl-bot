"""Internationalization support for multi-language messages."""

MESSAGES = {
    "zh": {
        "empty_input": "请输入您想要访问的网址，例如：`google.com 请给我代理地址`",
        "no_url_detected": (
            "未检测到有效的网址。请输入您想要访问的网址，例如：\n"
            "• `google.com 请给我代理地址`\n"
            "• `https://example.com 帮我生成访问链接`"
        ),
        "url_detected_no_proxy": "检测到网址：{urls}\n如果您需要代理访问链接，请说：`{example_url} 请给我代理地址`",
        "proxy_generated_header": "\n*代理链接已生成:*",
        "proxy_item": "\n• 原始网址: `{original_url}`\n  代理链接: {qurl_link}\n  有效期至: {expires_at}",
        "failed_header": "\n\n*以下网址处理失败:*",
        "failed_item": "• {url}: 生成失败 - {error}",
        "invalid_url": "• {url}: 无效的网址格式",
        "processing_error": "处理请求时发生错误，请稍后重试。错误信息: {error}",
        "welcome_title": "*欢迎使用 QURL 代理机器人!*",
        "welcome_body": (
            "这个机器人使用 AI 智能理解您的需求，帮助您生成安全的代理链接。\n\n"
            "*使用方法:*\n"
            "• 直接发送消息给我，或在频道中 @提及我\n"
            "• 用自然语言描述您的需求\n\n"
            "*示例:*\n"
            "• `我想访问 google.com，帮我生成代理链接`\n"
            "• `github.com 需要代理，有效期7天`\n"
            "• `帮我访问这个网站 https://example.com`"
        ),
    },
    "en": {
        "empty_input": "Please enter the URL you want to access, e.g.: `google.com I need a proxy`",
        "no_url_detected": (
            "No valid URL detected. Please enter the URL you want to access, e.g.:\n"
            "• `google.com I need a proxy`\n"
            "• `https://example.com generate access link`"
        ),
        "url_detected_no_proxy": "Detected URL: {urls}\nIf you need a proxy link, please say: `{example_url} I need a proxy`",
        "proxy_generated_header": "\n*Proxy link generated:*",
        "proxy_item": "\n• Original URL: `{original_url}`\n  Proxy link: {qurl_link}\n  Expires at: {expires_at}",
        "failed_header": "\n\n*The following URLs failed:*",
        "failed_item": "• {url}: Generation failed - {error}",
        "invalid_url": "• {url}: Invalid URL format",
        "processing_error": "An error occurred while processing your request. Please try again later. Error: {error}",
        "welcome_title": "*Welcome to QURL Proxy Bot!*",
        "welcome_body": (
            "This bot uses AI to understand your needs and help you generate secure proxy links.\n\n"
            "*How to use:*\n"
            "• Send me a direct message or @mention me in a channel\n"
            "• Describe your needs in natural language\n\n"
            "*Examples:*\n"
            "• `I want to access google.com, generate a proxy link`\n"
            "• `github.com need proxy, valid for 7 days`\n"
            "• `Help me access this website https://example.com`"
        ),
    },
}


def get_message(key: str, lang: str = "en", **kwargs) -> str:
    """
    Get a localized message.

    Args:
        key: Message key
        lang: Language code ("zh" for Chinese, "en" for English)
        **kwargs: Format arguments for the message

    Returns:
        Localized and formatted message
    """
    # Default to English if language not supported
    if lang not in MESSAGES:
        lang = "en"

    messages = MESSAGES[lang]
    message = messages.get(key, MESSAGES["en"].get(key, key))

    if kwargs:
        try:
            return message.format(**kwargs)
        except KeyError:
            return message

    return message


def is_chinese(lang: str) -> bool:
    """Check if the language is Chinese."""
    return lang.lower().startswith("zh")
