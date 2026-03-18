"""
Discord adapter for QURL proxy bot.
"""

import asyncio
import logging
import re

import discord
import httpx
from discord import app_commands

from config import settings
from core.bot_core import (
    process_message,
    analyze_message,
    build_proxy_reply,
    _dashboard_reply,
    handle_setkey,
    handle_mykey,
    handle_delkey,
    preprocess_text,
    PLATFORM_DISCORD,
)
from services.time_utils import get_timezone_from_discord_locale, format_utc_to_local
from services.upload_client import upload_file, extract_resource_id_from_url
from services.mint_link_client import mint_links


async def _handle_file_upload(bot: discord.Client, message: discord.Message, is_dm: bool) -> None:
    """Download attachments, upload to API, send QURL links."""
    locale = getattr(message.author, "locale", None)
    lang = "zh" if locale and str(locale).startswith("zh") else "en"
    user_tz = get_timezone_from_discord_locale(locale)

    results = []
    errors = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for att in message.attachments:
            try:
                r = await client.get(att.url)
                r.raise_for_status()
                file_bytes = r.content
            except Exception as e:
                logger.warning(f"Failed to download attachment {att.filename}: {e}")
                errors.append(get_i18n_msg("upload_failed", lang, filename=att.filename, error=str(e)))
                continue
            ct = att.content_type or "application/octet-stream"
            result = await upload_file(file_bytes, att.filename, ct)
            if not result.success:
                errors.append(get_i18n_msg("upload_failed", lang, filename=att.filename, error=result.error or "Unknown"))
                continue
            link = result.qurl_link or result.resource_url
            if link:
                exp = format_utc_to_local(result.expires_at, user_tz=user_tz) if result.expires_at else "-"
                results.append((att.filename, result, exp, link))
            else:
                errors.append(get_i18n_msg("upload_failed", lang, filename=att.filename, error=result.error or "No link"))

    if not results and not errors:
        msg = get_i18n_msg("upload_not_configured", lang)
        reply = f"{message.author.mention} {msg}" if not is_dm else msg
        await message.channel.send(reply)
        return

    if not results:
        # Failure: only output in channel, never DM anyone
        msg = "\n".join(errors)
        reply = f"{message.author.mention} {msg}" if not is_dm else msg
        await message.channel.send(reply)
        return

    # Success: build success message (new format)
    blocks = []
    for filename, res, exp_display, link in results:
        resource_id_display = res.resource_id or extract_resource_id_from_url(link)
        block = [
            "📎 New File Available via Qurl",
            f"File: {filename}",
        ]
        if resource_id_display:
            block.append(f"Resource ID: {resource_id_display}")
        block.append(f"🔗 Qurl Access Link: {link}")
        block.append(f"⏳ Qurl Expiration: {exp_display}")
        blocks.append("\n".join(block))
    success_msg = "\n\n".join(blocks)
    if errors:
        success_msg += "\n\n" + "\n".join(errors)

    if is_dm:
        await message.channel.send(success_msg)
        return

    # In channel: DM each @mentioned user, then reply in channel
    mentioned_users = [m for m in message.mentions if bot.user and m.id != bot.user.id]
    dm_targets = mentioned_users if mentioned_users else [message.author]

    success_dmed = []
    for target in dm_targets:
        try:
            await target.send(success_msg)
            success_dmed.append(target)
        except discord.Forbidden:
            logger.warning(f"Cannot DM Discord user {target} (id: {target.id})")

    if success_dmed:
        if mentioned_users:
            mentions = " ".join(u.mention for u in success_dmed)
            await message.channel.send(
                f"{message.author.mention} {get_i18n_msg('dm_sent_to_users', lang, users=mentions)}"
            )
        else:
            await message.channel.send(
                f"{message.author.mention} {get_i18n_msg('dm_sent', lang)}"
            )
    else:
        await message.channel.send(
            f"{message.author.mention} {get_i18n_msg('dm_failed', lang)}"
        )


def _extract_resource_id(text: str) -> str | None:
    """Extract resource_id from message. Supports res_xxx or alphanumeric 8-20 chars."""
    if not text or not text.strip():
        return None
    # res_abc123 format
    m = re.search(r"res_[a-zA-Z0-9]+", text, re.IGNORECASE)
    if m:
        return m.group()
    # rkrdrn7o79c format (8-20 alphanumeric)
    m = re.search(r"\b[a-zA-Z0-9]{8,20}\b", text)
    return m.group() if m else None


async def _handle_mint_link(bot: discord.Client, message: discord.Message) -> None:
    """Generate qurl links from resource_id in channel, DM each recipient."""
    locale = getattr(message.author, "locale", None)
    lang = "zh" if locale and str(locale).startswith("zh") else "en"
    user_tz = get_timezone_from_discord_locale(locale)

    clean_text = preprocess_text(message.content or "", PLATFORM_DISCORD)
    resource_id = _extract_resource_id(clean_text)

    if not resource_id:
        hint = get_i18n_msg("mint_link_no_resource_id", lang)
        await message.channel.send(f"{message.author.mention} {hint}")
        return

    mentioned_users = [m for m in message.mentions if bot.user and m.id != bot.user.id]
    dm_targets = mentioned_users if mentioned_users else [message.author]
    n = len(dm_targets)

    result = await mint_links(resource_id, n=n)

    if not result.success:
        err_msg = get_i18n_msg("mint_link_error", lang, error=result.error or "Unknown")
        await message.channel.send(f"{message.author.mention} {err_msg}")
        return

    links = result.links
    if len(links) < n:
        n = len(links)

    success_dmed = []
    for i, target in enumerate(dm_targets):
        if i >= len(links):
            break
        item = links[i]
        qurl_link = item.get("qurl_link")
        expires_at = item.get("expires_at")
        if not qurl_link:
            continue
        exp_display = format_utc_to_local(expires_at, user_tz=user_tz) if expires_at else "-"
        block = [
            "📎 Link Generated via Qurl",
            f"🔗 Qurl Access Link: {qurl_link}",
            f"⏳ Qurl Expiration: {exp_display}",
        ]
        success_msg = "\n".join(block)
        try:
            await target.send(success_msg)
            success_dmed.append(target)
        except discord.Forbidden:
            logger.warning(f"Cannot DM Discord user {target} (id: {target.id})")

    if success_dmed:
        if mentioned_users:
            mentions = " ".join(u.mention for u in success_dmed)
            await message.channel.send(
                f"{message.author.mention} {get_i18n_msg('dm_sent_to_users', lang, users=mentions)}"
            )
        else:
            await message.channel.send(
                f"{message.author.mention} {get_i18n_msg('dm_sent', lang)}"
            )
    else:
        await message.channel.send(
            f"{message.author.mention} {get_i18n_msg('dm_failed', lang)}"
        )


def _parse_command(text: str) -> tuple[str | None, str]:
    """Parse /setkey, /mykey, /delkey from message text."""
    t = text.strip()
    if t.startswith("/setkey"):
        return ("setkey", t[7:].strip())
    if t.startswith("/mykey"):
        return ("mykey", "")
    if t.startswith("/delkey"):
        return ("delkey", "")
    return (None, "")

logger = logging.getLogger(__name__)


class QURLDiscordBot(discord.Client):
    """Discord bot for QURL proxy generation."""

    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        """Register slash commands. Discord-only mode: file upload only, no setkey/mykey/delkey."""
        # setkey_cmd, mykey_cmd, delkey_cmd - disabled for Discord (file upload only)
        # self.tree.add_command(setkey_cmd)
        # self.tree.add_command(mykey_cmd)
        # self.tree.add_command(delkey_cmd)
        await self.tree.sync()

    async def on_ready(self):
        logger.info(f"Discord bot logged in as {self.user}")
        logger.info(
            "[Discord] Platform limitations: "
            "user email not available (API restriction); "
            "user timezone inferred from locale when possible, defaults to UTC; "
            "App Home not supported (no Discord equivalent)"
        )

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = self.user and self.user.mentioned_in(message)

        if not (is_dm or is_mention):
            return

        text = message.content or ""
        clean_text = preprocess_text(text, PLATFORM_DISCORD)
        locale = getattr(message.author, "locale", None)
        lang = "zh" if locale and str(locale).startswith("zh") else "en"

        # Channel: no file upload, only resource_id -> mint_link
        if not is_dm:
            if message.attachments:
                msg = get_i18n_msg("upload_channel_disabled", lang)
                await message.channel.send(f"{message.author.mention} {msg}")
                return
            # Channel: try resource_id to generate links
            resource_id = _extract_resource_id(clean_text)
            if resource_id:
                await _handle_mint_link(self, message)
                return
            hint = get_i18n_msg("mint_link_prompt", lang)
            await message.channel.send(f"{message.author.mention} {hint}")
            return

        # DM: file upload when attachments exist
        if message.attachments:
            if settings.upload_api_url:
                await _handle_file_upload(self, message, is_dm=True)
                return
            msg = get_i18n_msg("upload_not_configured", lang)
            await message.channel.send(msg)
            return

        # DM, no attachments
        hint = get_i18n_msg("upload_only_prompt", lang)
        await message.channel.send(hint)


def get_empty_msg() -> str:
    from services.i18n import get_message
    return get_message("empty_input", "en")


def get_i18n_msg(key: str, lang: str = "en", **kwargs) -> str:
    from services.i18n import get_message
    return get_message(key, lang, **kwargs)


@app_commands.command(name="setkey", description="Configure your LayerV API Key")
@app_commands.describe(api_key="Your LayerV API Key from https://layerv.ai/qurl/dashboard/keys")
async def setkey_cmd(interaction: discord.Interaction, api_key: str):
    await interaction.response.defer(ephemeral=True)
    msg, _ = await handle_setkey(str(interaction.user.id), api_key.strip(), PLATFORM_DISCORD)
    await interaction.followup.send(msg, ephemeral=True)


@app_commands.command(name="mykey", description="Show your API key status")
async def mykey_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_tz = get_timezone_from_discord_locale(interaction.user.locale)
    msg, _ = await handle_mykey(
        str(interaction.user.id),
        PLATFORM_DISCORD,
        user_tz=user_tz,
    )
    await interaction.followup.send(msg, ephemeral=True)


@app_commands.command(name="delkey", description="Delete your API key")
async def delkey_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    msg, _ = await handle_delkey(str(interaction.user.id), PLATFORM_DISCORD)
    await interaction.followup.send(msg, ephemeral=True)


def run_discord_bot():
    """Run Discord bot. Blocks until shutdown. Use for Discord-only mode."""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.dm_messages = True

    bot = QURLDiscordBot(intents=intents)
    bot.run(settings.discord_token)


async def run_discord_async():
    """Run Discord bot as async task. Use when running alongside Slack."""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.dm_messages = True

    bot = QURLDiscordBot(intents=intents)
    await bot.start(settings.discord_token)
