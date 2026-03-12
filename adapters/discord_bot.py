"""
Discord adapter for QURL proxy bot.
"""

import asyncio
import logging
import re

import discord
from discord import app_commands

from config import settings
from core.bot_core import process_message, handle_setkey, handle_mykey, handle_delkey
from core.bot_core import preprocess_text, PLATFORM_DISCORD
from services.time_utils import get_timezone_from_discord_locale

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

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # DMs or when bot is mentioned in a channel
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = self.user and self.user.mentioned_in(message)

        if not (is_dm or is_mention):
            return

        text = message.content
        if not text:
            await message.channel.send(get_empty_msg())
            return

        # Remove bot mention from text
        clean_text = preprocess_text(text, PLATFORM_DISCORD)
        if not clean_text and is_mention:
            await message.channel.send("Please include your request, e.g. `google.com I need a proxy`")
            return

        user_id = str(message.author.id)
        user_tz = get_timezone_from_discord_locale(message.author.locale)

        reply_content, _ = await process_message(
            clean_text, user_id, PLATFORM_DISCORD, user_tz=user_tz
        )

        # Prefix with user mention for channel replies
        if is_mention:
            reply_content = f"{message.author.mention} {reply_content}"

        await message.channel.send(reply_content)


def get_empty_msg() -> str:
    from services.i18n import get_message
    return get_message("empty_input", "en")


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
