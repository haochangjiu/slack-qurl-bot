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
        # API Key commands
        "no_api_key": (
            "⚠️ 您还未配置 API Key。\n"
            "请先私信我并使用 `/setkey <your_api_key>` 命令配置您的 LayerV API Key。\n\n"
            "获取 API Key: https://layerv.ai/console"
        ),
        "setkey_usage": "用法: `/setkey <your_api_key>`\n\n从 LayerV 控制台获取您的 API Key: https://layerv.ai/console",
        "setkey_success": "✅ API Key 配置成功！现在可以使用 QURL 服务了。",
        "setkey_invalid": "❌ API Key 无效，请检查后重试。",
        "setkey_error": "❌ 配置 API Key 时发生错误: {error}",
        "mykey_info": "🔑 您的 API Key: `{prefix}`\n配置时间: {created_at}",
        "mykey_none": "您还未配置 API Key。使用 `/setkey <your_api_key>` 进行配置。",
        "delkey_success": "✅ API Key 已删除。",
        "delkey_none": "您没有配置 API Key。",
        "invalid_api_key": "❌ 您的 API Key 已失效，请使用 `/setkey <new_api_key>` 重新配置。",
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
        # API Key commands
        "no_api_key": (
            "⚠️ You haven't configured your API Key yet.\n"
            "Please DM me and use `/setkey <your_api_key>` to configure your LayerV API Key.\n\n"
            "Get your API Key: https://layerv.ai/console"
        ),
        "setkey_usage": "Usage: `/setkey <your_api_key>`\n\nGet your API Key from LayerV console: https://layerv.ai/console",
        "setkey_success": "✅ API Key configured successfully! You can now use the QURL service.",
        "setkey_invalid": "❌ Invalid API Key. Please check and try again.",
        "setkey_error": "❌ Error configuring API Key: {error}",
        "mykey_info": "🔑 Your API Key: `{prefix}`\nConfigured at: {created_at}",
        "mykey_none": "You haven't configured an API Key. Use `/setkey <your_api_key>` to configure.",
        "delkey_success": "✅ API Key deleted.",
        "delkey_none": "You don't have an API Key configured.",
        "invalid_api_key": "❌ Your API Key is invalid or expired. Please use `/setkey <new_api_key>` to reconfigure.",
    },
}


def normalize_language(lang: str) -> str:
    """
    Normalize language code to 'zh' or 'en'.

    Args:
        lang: Raw language code from AI

    Returns:
        Normalized language code ('zh' or 'en')
    """
    if not lang:
        return "en"

    lang_lower = lang.lower()

    # Check for Chinese
    chinese_indicators = ["zh", "chinese", "中文", "cn", "mandarin"]
    for indicator in chinese_indicators:
        if indicator in lang_lower:
            return "zh"

    # Default to English for everything else
    return "en"


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
    # Normalize language code
    lang = normalize_language(lang)

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
    return normalize_language(lang) == "zh"
