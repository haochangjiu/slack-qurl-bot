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
from services.upload_client import upload_file, upload_google_map, extract_resource_id_from_url
from services.mint_link_client import mint_links
from services.resource_store import init_db, record_resource, get_resource, is_owner, is_expired, record_mint_link, list_resources_by_owner, get_mint_links_for_resource, delete_resource
from services.google_maps_resolver import resolve_google_map

_GOOGLE_MAPS_PATTERN = re.compile(r"https://maps\.app\.goo\.gl/[^\s<>)\]\"']+", re.IGNORECASE)
_GOOGLE_MAPS_EMBED_PATTERN = re.compile(r"https://www\.google\.com/maps/embed[^\s<>)\]\"']+", re.IGNORECASE)

# ---------------------------------------------------------------------------
# 数据库初始化（启动时调用一次）
# ---------------------------------------------------------------------------

init_db()


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _discord_name(user: discord.User | discord.Member) -> str:
    """
    返回该 Discord 用户的稳定标识名。

    优先使用 global_name（显示名称），fallback 到 "name#discriminator" 格式
    （discriminator 为 0 时表示新版账号，改用 name 本身）。
    """
    if user.discriminator != "0":
        return f"{user.name}#{user.discriminator}"
    return getattr(user, "global_name", None) or user.name


def _can_share(
    resource_id: str,
    requester_id: str,
    requester_name: str,
) -> tuple[bool, str]:
    """
    判断申请人是否有权为该 resource_id 生成 mint link。

    规则：
      1. 资源不存在 → 禁止
      2. 资源已过期 → 禁止
      3. 申请人是拥有人 → 允许
      4. 申请人不是拥有人 → 禁止
    """
    # 不存在
    res = get_resource(resource_id)
    if not res:
        return False, "not_found"

    # 已过期
    expired, exp_str = is_expired(resource_id)
    if expired:
        return False, "expired"

    # 权限检查（同时匹配 discord_id 或 discord_name）
    if not is_owner(resource_id, requester_id, requester_name):
        return False, "forbidden"

    return True, ""


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


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

            # 记录到本地 SQLite
            rid = result.resource_id or extract_resource_id_from_url(result.qurl_link or result.resource_url)
            if rid:
                record_resource(
                    resource_id=rid,
                    discord_id=str(message.author.id),
                    discord_name=_discord_name(message.author),
                    md5_hash=result.md5_hash,
                    file_type="file",
                    expires_at=result.expires_at,
                )
            else:
                logger.warning(
                    f"[discord_bot] Could not extract resource_id for {att.filename}, "
                    f"qurl_link={result.qurl_link}, resource_url={result.resource_url}"
                )

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


async def _handle_google_map_upload(bot: discord.Client, message: discord.Message, google_map_url: str, is_dm: bool) -> None:
    """Resolve Google Maps short URL, upload to API, send QURL links."""
    locale = getattr(message.author, "locale", None)
    lang = "zh" if locale and str(locale).startswith("zh") else "en"
    user_tz = get_timezone_from_discord_locale(locale)

    # Step 1: Resolve to embed URL (needed for DB record)
    resolved = await resolve_google_map(google_map_url)
    embed_url = resolved.embed_url or resolved.resolved_url or google_map_url

    # Step 2: Upload
    result = await upload_google_map(google_map_url)
    if not result.success:
        msg = get_i18n_msg("google_map_upload_failed", lang, url=google_map_url, error=result.error or "Unknown")
        reply = f"{message.author.mention} {msg}" if not is_dm else msg
        await message.channel.send(reply)
        return

    link = result.qurl_link or result.resource_url
    if not link:
        msg = get_i18n_msg("google_map_upload_failed", lang, url=google_map_url, error="No link")
        reply = f"{message.author.mention} {msg}" if not is_dm else msg
        await message.channel.send(reply)
        return

    # 记录到本地 SQLite
    rid = result.resource_id or extract_resource_id_from_url(link)
    if rid:
        record_resource(
            resource_id=rid,
            discord_id=str(message.author.id),
            discord_name=_discord_name(message.author),
            file_type="google-map",
            embed_url=embed_url,
            expires_at=result.expires_at,
        )
    else:
        logger.warning(
            f"[discord_bot] Could not extract resource_id for google_map {google_map_url}, "
            f"qurl_link={link}"
        )

    resource_id_display = result.resource_id or extract_resource_id_from_url(link)
    exp = format_utc_to_local(result.expires_at, user_tz=user_tz) if result.expires_at else "-"

    block = [
        "🗺️ New Google Map Available via Qurl",
    ]
    if resource_id_display:
        block.append(f"Resource ID: {resource_id_display}")
    block.append(f"🔗 Qurl Access Link: {link}")
    block.append(f"⏳ Qurl Expiration: {exp}")
    success_msg = "\n".join(block)

    if is_dm:
        await message.channel.send(success_msg)
        return

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
    """
    Extract resource_id from message text.

    Supports formats:
      - r_abc123-def          (r_ prefix, 8-64 lowercase alphanumeric + underscores + hyphens after)
      - res_abc123           (res_ prefix, lowercase alphanumeric)
      - hex hash (32 or 64 chars) for backwards compat
    """
    if not text or not text.strip():
        return None
    # r_abc123_def format — r_ prefix, lowercase + digits + underscores + hyphens (8-64 chars)
    m = re.search(r"\br_[a-z0-9_-]{8,64}\b", text)
    if m:
        return m.group()
    # res_abc123 format
    m = re.search(r"\bres_[a-zA-Z0-9]+\b", text, re.IGNORECASE)
    if m:
        return m.group()
    # hex hash (md5 32, sha256 64)
    m = re.search(r"\b[a-fA-F0-9]{32,64}\b", text)
    if m:
        return m.group()
    return None


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

    # 权限 + 过期检查
    allowed, reason = _can_share(resource_id, str(message.author.id), _discord_name(message.author))
    if not allowed:
        if reason == "not_found":
            err_msg = (
                f"⚠️ 资源 `{resource_id}` 不存在或尚未上传记录。"
                if lang == "zh"
                else f"⚠️ Resource `{resource_id}` not found."
            )
        elif reason == "expired":
            err_msg = (
                f"⚠️ 资源 `{resource_id}` 已过期。"
                if lang == "zh"
                else f"⚠️ Resource `{resource_id}` has expired."
            )
        else:
            err_msg = (
                f"⚠️ 你不是资源 `{resource_id}` 的上传者，无权分发。"
                if lang == "zh"
                else f"⚠️ You are not the owner of resource `{resource_id}`. Only the uploader can distribute this resource."
            )
        # 私信说明原因
        try:
            await message.author.send(err_msg)
        except discord.Forbidden:
            pass
        await message.channel.send(f"{message.author.mention} {err_msg}")
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
            # 仅 DM 成功后才记录到数据库
            record_mint_link(
                resource_id=resource_id,
                discord_id=str(target.id),
                discord_name=_discord_name(target),
                qurl_link=qurl_link,
                expires_at=expires_at,
            )
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
        self.tree.add_command(qurl_group)
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

        # DM: check for resource_id first (mint link, with ownership check)
        if _extract_resource_id(clean_text):
            await _handle_mint_link(self, message)
            return

        # DM: file upload when attachments exist
        if message.attachments:
            if settings.upload_api_url:
                await _handle_file_upload(self, message, is_dm=True)
                return
            msg = get_i18n_msg("upload_not_configured", lang)
            await message.channel.send(msg)
            return

        # DM: check for Google Maps URL
        google_map_match = _GOOGLE_MAPS_PATTERN.search(message.content or "")
        google_maps_embed_match = _GOOGLE_MAPS_EMBED_PATTERN.search(message.content or "")
        if google_map_match and settings.upload_api_url:
            await _handle_google_map_upload(self, message, google_map_match.group(), is_dm=True)
            return
        if google_maps_embed_match and settings.upload_api_url:
            await _handle_google_map_upload(self, message, google_maps_embed_match.group(), is_dm=True)
            return

        # DM: check for /qurl help command
        if re.search(r"^/qurl\s+help\b", text, re.IGNORECASE):
            await message.channel.send(_QURL_HELP_MSG)
            return

        # DM, no attachments and no Google Map
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


_QURL_HELP_MSG = """📖 Qurl Bot — Help

DM a file to @QurlBot to protect it. You'll receive a
resource_id and a secure link back.

To send individual links to users in a server:
  @QurlBot #<resource_id> @user1 @user2 ...

Slash commands:
  /qurl list              — list your protected files
  /qurl status <id>       — check link usage for a file
  /qurl revoke <id>       — revoke a file and all its links
  /qurl help              — show this message

Each recipient receives their own unique, single-use link
by DM. Links self-destruct on access."""


@app_commands.command(name="help", description="Show help and usage instructions")
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(_QURL_HELP_MSG)


# ---------------------------------------------------------------------------
# /qurl list
# ---------------------------------------------------------------------------

@app_commands.command(
    name="list",
    description="List all files you have uploaded",
)
async def qurl_list_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    discord_id = str(interaction.user.id)
    discord_name = _discord_name(interaction.user)
    locale = getattr(interaction.user, "locale", None)
    lang = "zh" if locale and str(locale).startswith("zh") else "en"

    resources = list_resources_by_owner(discord_id, discord_name)

    if not resources:
        if lang == "zh":
            msg = "📂 你还没有上传过任何文件。"
        else:
            msg = "📂 You haven't uploaded any files yet."
        await interaction.followup.send(msg, ephemeral=True)
        return

    lines = []
    for r in resources:
        rid = r.get("resource_id", "?")
        ftype = r.get("file_type", "file")
        created = r.get("created_at", "-")
        exp = r.get("expires_at", None)

        if lang == "zh":
            type_label = "🗺️ Google 地图" if ftype == "google-map" else "📎 文件"
            exp_display = f" | ⏳ {exp}" if exp else " | ⏳ 不过期"
            lines.append(f"**{rid}**\n  {type_label} | 上传于 {created}{exp_display}")
        else:
            type_label = "🗺️ Google Map" if ftype == "google-map" else "📎 File"
            exp_display = f" | ⏳ {exp}" if exp else " | ⏳ No expiry"
            lines.append(f"**{rid}**\n  {type_label} | Uploaded {created}{exp_display}")

    header = "📂 你的上传记录" if lang == "zh" else "📂 Your Uploads"
    body = "\n\n".join(lines)
    await interaction.followup.send(f"{header}\n\n{body}", ephemeral=True)


# ---------------------------------------------------------------------------
# /qurl status
# ---------------------------------------------------------------------------

@app_commands.command(
    name="status",
    description="Check link usage for a specific resource",
)
@app_commands.describe(resource_id="The resource ID (e.g. r_abc123)")
async def qurl_status_cmd(interaction: discord.Interaction, resource_id: str):
    await interaction.response.defer(ephemeral=True)

    discord_id = str(interaction.user.id)
    discord_name = _discord_name(interaction.user)
    locale = getattr(interaction.user, "locale", None)
    lang = "zh" if locale and str(locale).startswith("zh") else "en"

    # 权限检查
    if not is_owner(resource_id, discord_id, discord_name):
        if lang == "zh":
            msg = f"⚠️ 你不是资源 `{resource_id}` 的上传者，无法查看。"
        else:
            msg = f"⚠️ You are not the owner of resource `{resource_id}`. Only the uploader can view this resource."
        await interaction.followup.send(msg, ephemeral=True)
        return

    res = get_resource(resource_id)
    if not res:
        if lang == "zh":
            msg = f"⚠️ 资源 `{resource_id}` 不存在。"
        else:
            msg = f"⚠️ Resource `{resource_id}` not found."
        await interaction.followup.send(msg, ephemeral=True)
        return

    mint_links = get_mint_links_for_resource(resource_id)

    # 构建资源信息
    ftype = res.get("file_type", "file")
    created = res.get("created_at", "-")
    exp = res.get("expires_at", None)
    uploader_name = res.get("discord_name", "-")

    if lang == "zh":
        type_label = "🗺️ Google 地图" if ftype == "google-map" else "📎 文件"
        exp_display = exp if exp else "不过期"
        header = f"📊 资源状态 — `{resource_id}`"
        meta = [
            f"类型: {type_label}",
            f"上传者: {uploader_name}",
            f"上传时间: {created}",
            f"过期时间: {exp_display}",
        ]
    else:
        type_label = "🗺️ Google Map" if ftype == "google-map" else "📎 File"
        exp_display = exp if exp else "No expiry"
        header = f"📊 Resource Status — `{resource_id}`"
        meta = [
            f"Type: {type_label}",
            f"Uploader: {uploader_name}",
            f"Uploaded: {created}",
            f"Expires: {exp_display}",
        ]

    # 构建链接列表
    if mint_links:
        link_lines = []
        for link in mint_links:
            lnk = link.get("qurl_link", "?")
            recipient = link.get("discord_name", "?")
            minted = link.get("minted_at", "-")
            link_exp = link.get("expires_at", "-")
            if lang == "zh":
                link_lines.append(
                    f"  • {lnk}\n    接收人: {recipient} | 生成时间: {minted} | 链接过期: {link_exp}"
                )
            else:
                link_lines.append(
                    f"  • {lnk}\n    Recipient: {recipient} | Minted: {minted} | Expires: {link_exp}"
                )
        if lang == "zh":
            links_header = f"\n已分发的链接 ({len(mint_links)} 条)："
            links_body = "\n".join(link_lines)
        else:
            links_header = f"\nDistributed links ({len(mint_links)}):"
            links_body = "\n".join(link_lines)
    else:
        links_header = ""
        links_body = ""

    meta_str = "\n".join(meta)
    full_msg = f"{header}\n{meta_str}{links_header}\n{links_body}"
    await interaction.followup.send(full_msg, ephemeral=True)


# ---------------------------------------------------------------------------
# /qurl revoke
# ---------------------------------------------------------------------------

@app_commands.command(
    name="revoke",
    description="Revoke a resource and all its distributed links",
)
@app_commands.describe(resource_id="The resource ID to revoke")
async def qurl_revoke_cmd(interaction: discord.Interaction, resource_id: str):
    await interaction.response.defer(ephemeral=True)

    discord_id = str(interaction.user.id)
    discord_name = _discord_name(interaction.user)
    locale = getattr(interaction.user, "locale", None)
    lang = "zh" if locale and str(locale).startswith("zh") else "en"

    # 权限检查
    if not is_owner(resource_id, discord_id, discord_name):
        if lang == "zh":
            msg = f"⚠️ 你不是资源 `{resource_id}` 的上传者，无法删除。"
        else:
            msg = f"⚠️ You are not the owner of resource `{resource_id}`. Only the uploader can revoke this resource."
        await interaction.followup.send(msg, ephemeral=True)
        return

    res = get_resource(resource_id)
    if not res:
        if lang == "zh":
            msg = f"⚠️ 资源 `{resource_id}` 不存在。"
        else:
            msg = f"⚠️ Resource `{resource_id}` not found."
        await interaction.followup.send(msg, ephemeral=True)
        return

    success, mint_count, res_count = delete_resource(resource_id)

    if success:
        if lang == "zh":
            msg = (
                f"✅ 资源 `{resource_id}` 已删除。\n"
                f"  同时删除了 {mint_count} 条链接记录。"
            )
        else:
            msg = (
                f"✅ Resource `{resource_id}` has been revoked.\n"
                f"  {mint_count} associated link record(s) were also deleted."
            )
    else:
        if lang == "zh":
            msg = f"❌ 删除资源 `{resource_id}` 失败，请稍后重试。"
        else:
            msg = f"❌ Failed to revoke resource `{resource_id}`. Please try again later."

    await interaction.followup.send(msg, ephemeral=True)


qurl_group = app_commands.Group(name="qurl", description="Qurl Bot commands")
qurl_group.add_command(help_cmd)
qurl_group.add_command(qurl_list_cmd)
qurl_group.add_command(qurl_status_cmd)
qurl_group.add_command(qurl_revoke_cmd)


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
