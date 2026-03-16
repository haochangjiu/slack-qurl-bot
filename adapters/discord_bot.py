"""
Discord adapter for QURL proxy bot.
"""

import asyncio
import logging
import re

import discord
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
from services.time_utils import get_timezone_from_discord_locale


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
        """Register slash commands."""
        self.tree.add_command(setkey_cmd)
        self.tree.add_command(mykey_cmd)
        self.tree.add_command(delkey_cmd)
        # Sync globally - can take up to 1 hour. For testing use guild-specific.
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

        text = message.content
        if not text:
            await message.channel.send(get_empty_msg())
            return

        clean_text = preprocess_text(text, PLATFORM_DISCORD)
        if not clean_text and is_mention:
            await message.channel.send("Please include your request, e.g. `google.com I need a proxy`")
            return

        user_id = str(message.author.id)
        locale = getattr(message.author, "locale", None)
        user_tz = get_timezone_from_discord_locale(locale)
        if not user_tz:
            logger.debug(f"Discord user {message.author} (id: {user_id}): timezone unavailable (locale={locale}), using UTC")
        logger.info(
            f"Discord {'DM' if is_dm else 'mention'} from {message.author} (id: {user_id}): {clean_text}"
        )

        cmd, arg = _parse_command(clean_text)
        if cmd:
            if cmd == "setkey":
                msg, _ = await handle_setkey(user_id, arg, PLATFORM_DISCORD)
            elif cmd == "mykey":
                msg, _ = await handle_mykey(user_id, PLATFORM_DISCORD, user_tz=user_tz)
            else:
                msg, _ = await handle_delkey(user_id, PLATFORM_DISCORD)
            if is_dm:
                await message.channel.send(msg)
            else:
                await message.channel.send(f"{message.author.mention} {msg}")
            return

        if is_dm:
            # Analyze (includes dashboard shortcut check)
            analysis = await analyze_message(clean_text, user_id, PLATFORM_DISCORD)
            if "dashboard" in analysis:
                await message.channel.send(_dashboard_reply(analysis["lang"]))
                return
            if "error" in analysis:
                await message.channel.send(analysis["error"])
                return
            reply, _ = await build_proxy_reply(
                analysis["urls"], analysis["api_key"], analysis["expires_in"],
                analysis["reason"], analysis["lang"], PLATFORM_DISCORD, user_id, user_tz=user_tz,
            )
            await message.channel.send(reply)
        else:
            mentioned_users = [
                m for m in message.mentions
                if m.id != self.user.id
            ]

            # Analyze once (AI + URL extraction)
            analysis = await analyze_message(clean_text, user_id, PLATFORM_DISCORD)
            if "dashboard" in analysis:
                await message.channel.send(
                    f"{message.author.mention} {_dashboard_reply(analysis['lang'])}"
                )
                return
            if "error" in analysis:
                await message.channel.send(
                    f"{message.author.mention} {analysis['error']}"
                )
                return

            lang = analysis["lang"]
            dm_targets = mentioned_users if mentioned_users else [message.author]

            success = []
            for target in dm_targets:
                # Generate unique proxy links per recipient
                reply, _ = await build_proxy_reply(
                    analysis["urls"], analysis["api_key"], analysis["expires_in"],
                    analysis["reason"], lang, PLATFORM_DISCORD, user_id, user_tz=user_tz,
                )
                try:
                    if target.id == message.author.id:
                        await target.send(reply)
                    else:
                        logger.info(f"Sending proxy to Discord user {target} (id: {target.id})")
                        header = get_i18n_msg(
                            "dm_proxy_for_you", lang, from_user=message.author.display_name
                        )
                        await target.send(f"{header}\n{reply}")
                    success.append(target)
                except discord.Forbidden:
                    logger.warning(f"Cannot DM Discord user {target} (id: {target.id})")

            if success:
                if mentioned_users:
                    mentions = " ".join(u.mention for u in success)
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
