# Qurl Bot — Design Document

## 1. Overview

Qurl Bot is a multi-platform chatbot (Slack + Discord) that generates secure, time-limited QURL proxy links on demand. When a user mentions `@qurl <url or website name>` in a channel or sends a direct message, the bot uses an Atlas Cloud hosted LLM to interpret the user's intent and extract the target URL, then calls LayerV's QURL API to generate a cryptographic access link. The proxy link is delivered via DM for privacy.

**Key properties of a QURL:**
- Identity-verified: only issued to confirmed workspace/server members
- Time-limited: automatically expires after a configurable period (default 30 minutes)
- Invisible: wraps the target behind a non-guessable, non-indexed address
- Single-session: self-destructs when the session ends or time expires

**Supported platforms:**
- Slack (via Socket Mode)
- Discord (via Gateway with Message Content Intent)
- Both can run simultaneously from a single process

---

## 2. Architecture

### 2.1 Actors

| Actor | Role |
|---|---|
| **User** | Slack workspace member or Discord server member who requests a QURL via @mention or DM, in natural language |
| **Qurl Bot** | Python application that handles the mention/DM, interprets the URL via LLM, and calls LayerV |
| **LLM (Atlas Cloud)** | Extracts well-formed URLs from the user's natural language message, detects language and intent |
| **Slack API** | Used by the bot to receive events (Socket Mode), get user info (timezone, email), and send messages |
| **Discord API** | Used by the bot to receive events (Gateway), send messages, and register slash commands |
| **LayerV Backend** | Receives the QURL request, verifies the identity, and generates the secure link |

### 2.2 Sequence Diagram

#### Slack Flow

```
User        Slack Adapter    Bot Core     LLM (Atlas)    LayerV API
 |               |              |              |              |
 |--@qurl msg--->|              |              |              |
 |               |--preprocess->|              |              |
 |               |              |--analyze---->|              |
 |               |              |<--urls,lang--|              |
 |               |              |              |              |
 |               |              |--POST /v1/qurls------------>|
 |               |              |<--{qurl_link, expires_at}---|
 |               |              |              |              |
 |               |<--reply------|              |              |
 |<---DM---------|              |              |              |
```

#### Discord Flow

```
User        Discord Adapter  Bot Core     LLM (Atlas)    LayerV API
 |               |              |              |              |
 |--@bot msg---->|              |              |              |
 |               |--preprocess->|              |              |
 |               |              |--analyze---->|              |
 |               |              |<--urls,lang--|              |
 |               |              |              |              |
 |               |              |--POST /v1/qurls------------>|
 |               |              |<--{qurl_link, expires_at}---|
 |               |              |              |              |
 |               |<--reply------|              |              |
 |<---DM---------|              |              |              |
```

#### Multi-User Mention Flow (Channel)

When a user @mentions the bot along with other users in a channel (e.g., `@bot @UserA @UserB google.com`), the bot generates a **unique** proxy link for each mentioned user and delivers them via DM:

```
User        Bot              LLM         LayerV API     UserA      UserB
 |           |                |              |            |           |
 |--@bot---->|                |              |            |           |
 |  @A @B    |--analyze----->|              |            |           |
 |  google   |<--urls--------|              |            |           |
 |           |                |              |            |           |
 |           |--create QURL (for A)-------->|            |           |
 |           |<--{qurl_link_1}--------------|            |           |
 |           |--create QURL (for B)-------->|            |           |
 |           |<--{qurl_link_2}--------------|            |           |
 |           |                |              |            |           |
 |           |--DM qurl_link_1------------------------------>|       |
 |           |--DM qurl_link_2-------------------------------------->|
 |<--confirm-|                |              |            |           |
```

### 2.3 LLM Interpretation

The bot passes the raw message text to an Atlas Cloud hosted LLM through its OpenAI-compatible API with a structured system prompt. The LLM returns a JSON object with:

| Field | Type | Description |
|---|---|---|
| `language` | `"en"` / `"zh"` | Detected language of the user's message |
| `urls` | `list[str]` | Extracted URLs (always with `https://` prefix) |
| `wants_proxy` | `bool` | Whether the user wants a proxy link (defaults to `true` if any website is mentioned) |
| `expires_in` | `str` / `null` | Requested validity period (e.g., `"1h"`, `"7d"`) |
| `reason` | `str` / `null` | Brief description of the request |

This allows natural language inputs such as:

| User types | LLM extracts |
|---|---|
| `@qurl pls create a qurl for Google` | `https://google.com` |
| `@qurl 帮我访问谷歌` | `https://google.com` |
| `@qurl github.com need proxy, valid for 7 days` | `https://github.com`, expires_in=`"7d"` |
| `@qurl open the Netflix page` | `https://netflix.com` |
| `@qurl stats.layerv.xyz` | `https://stats.layerv.xyz/` |

The bot also supports **custom domain aliases** via `domain_aliases.json`, which are injected into the LLM prompt and resolved as a post-processing step.

If the LLM cannot confidently extract a URL, the bot replies asking the user to clarify.

### 2.4 QURL Dashboard Shortcut

Users can request the QURL dashboard/status page with natural language (case-insensitive):

- English: "I want to access Qurl dashboard", "Get the stats of Qurl"
- Chinese: "查看qurl状态", "访问qurl面板", "给我qurl的链接"

The bot detects keywords (`dashboard`, `stats`, `status`, `状态`, `统计` etc.) combined with the word `qurl`. If the message also contains other URLs, domains, or website names, it is treated as a normal proxy request instead.

### 2.5 Verification Flow Detail

LayerV performs a two-step Slack verification upon receiving the QURL request:

1. **`auth.test`** — validates that the bot token is genuine and active. Returns the bot's `team_id`, confirming which workspace it belongs to.
2. **`users.lookupByEmail`** — looks up the claimed email in that workspace. Confirms the user is a real, non-deactivated, non-bot member.

If either call fails, the QURL is not generated and a 401 is returned to the bot.

---

## 3. Components

### 3.1 Qurl Bot

- **Runtime:** Python 3.12+
- **Frameworks:**
  - Slack: `slack-bolt` (async) with Socket Mode
  - Discord: `discord.py` with Gateway (Message Content Intent)
- **LLM:** Atlas Cloud relay (`https://api.atlascloud.ai/v1`) using an OpenAI-compatible chat completion model for natural language understanding
- **HTTP Client:** `httpx` (async) for LayerV API calls
- **Configuration:** `pydantic-settings` with `.env` file
- **Entry point:** `run.py` (unified, runs Slack and/or Discord based on configuration)

#### Project Structure

```
slack-qurl-bot/
├── run.py                    # Unified entry point (Slack + Discord)
├── app.py                    # Backward-compatible Slack-only entry point
├── config.py                 # Configuration management (pydantic-settings)
├── requirements.txt          # Python dependencies
├── deploy.sh                 # systemd deployment script
├── domain_aliases.json       # Custom domain alias mappings
├── .env.example              # Example environment variables
├── core/
│   └── bot_core.py           # Platform-agnostic bot logic
├── adapters/
│   ├── slack_app.py          # Slack adapter (Bolt events & commands)
│   └── discord_bot.py        # Discord adapter (discord.py events & commands)
├── services/
│   ├── ai_analyzer.py        # Atlas Cloud LLM integration for URL extraction
│   ├── layerv.py             # LayerV QURL API client
│   ├── url_parser.py         # Regex-based URL extraction & normalization
│   ├── time_utils.py         # Timezone conversion & time formatting
│   ├── user_store.py         # Encrypted API key storage (per-user)
│   ├── domain_resolver.py    # Custom domain alias resolver
│   └── i18n.py               # Internationalization (zh/en)
└── data/
    └── users.json            # Encrypted user API key data (auto-generated)
```

#### Core Module (`core/bot_core.py`)

Platform-agnostic bot logic shared by both adapters:

| Function | Description |
|---|---|
| `analyze_message()` | AI analysis + URL extraction + API key validation. Called once per request. |
| `build_proxy_reply()` | Generates QURL proxy links for given URLs. Called once per recipient for unique links. |
| `process_message()` | Single-user convenience wrapper: `analyze_message()` + `build_proxy_reply()`. |
| `handle_setkey()` | Handle `/setkey` command. Disabled for Slack (global key), per-user for Discord. |
| `handle_mykey()` | Handle `/mykey` command. Shows global key info for Slack, per-user info for Discord. |
| `handle_delkey()` | Handle `/delkey` command. Disabled for Slack (global key), per-user for Discord. |
| `preprocess_text()` | Strip platform-specific formatting (Slack links, mentions) from message text. |
| `detect_language()` | Simple language detection based on CJK character presence. |

#### Slack Adapter (`adapters/slack_app.py`)

| Feature | Implementation |
|---|---|
| **Connection** | Socket Mode (no public URL needed) |
| **Events** | `app_mention`, `message.im`, `app_home_opened` |
| **Slash Commands** | `/setkey`, `/mykey`, `/delkey` (disabled; returns admin-managed message) |
| **Text Commands** | `/setkey`, `/mykey`, `/delkey` parsed from channel @mentions and DMs |
| **Channel Mentions** | Proxy link delivered via DM to requester or @mentioned users |
| **DMs** | Proxy link replied directly in the DM conversation |
| **User Info** | Timezone and email retrieved via `users.info` API |
| **API Key** | Global, read from `.env` (`LAYERV_API_KEY`). Shared across all Slack users. |

**Required Slack Bot Token Scopes:**
- `app_mentions:read` — receive @mention events
- `chat:write` — send messages in channels
- `im:history` — read DM history
- `im:read` — read DM events
- `im:write` — send DMs
- `users:read` — read user info (timezone)
- `users:read.email` — access user email (optional, for logging)
- `commands` — register slash commands

#### Discord Adapter (`adapters/discord_bot.py`)

| Feature | Implementation |
|---|---|
| **Connection** | Gateway with `message_content` and `dm_messages` Privileged Intents |
| **Events** | `on_message` (DM and channel mention) |
| **Slash Commands** | `/setkey`, `/mykey`, `/delkey` (registered via `app_commands`) |
| **Text Commands** | `/setkey`, `/mykey`, `/delkey` parsed from channel @mentions and DMs |
| **Channel Mentions** | Proxy link delivered via DM to requester or @mentioned users |
| **DMs** | Proxy link replied directly in the DM conversation |
| **User Info** | Timezone inferred from locale (limited); email not available (API restriction) |
| **API Key** | Per-user, stored encrypted in `data/users.json`. Each user must `/setkey` their own key. |

**Required Discord Bot Permissions:**
- `Send Messages` — reply in channels
- `Read Message History` — read channel messages
- `View Channel` — view channel content

**Required Privileged Gateway Intents:**
- `Message Content Intent` — read message content in guild channels

**Required OAuth2 Scopes:**
- `bot` — bot user
- `applications.commands` — register slash commands

#### Platform Differences

| Feature | Slack | Discord |
|---|---|---|
| API Key | Global (`.env`) | Per-user (encrypted storage) |
| `/setkey`, `/delkey` | Disabled (admin-managed) | Enabled (per-user) |
| User timezone | Accurate (via `users.info` API) | Inferred from locale (approximate) |
| User email | Available (with `users:read.email` scope) | Not available (API restriction) |
| Time display (no TZ) | N/A (always has TZ from Slack) | Human-readable duration (e.g., "30 minutes") |
| App Home | Supported (welcome page) | Not supported (no Discord equivalent) |
| Connection mode | Socket Mode (no public URL) | Gateway (no public URL) |

### 3.2 LayerV Backend

- **Runtime:** Node.js
- **Framework:** Express
- **Endpoint:** `POST /v1/qurls`
- **Request body:**

```json
{
  "target_url":  "https://stats.layerv.xyz/",
  "expires_in":  "30m",
  "one_time_use": true,
  "description": "Generated via slack bot for user U12345"
}
```

- **Request headers:**

```
Authorization: Bearer <LAYERV_API_KEY>
Content-Type: application/json
```

- **Response body (201):**

```json
{
  "data": {
    "resource_id": "r_abc123xyz",
    "qurl_link":   "https://qurl.link/at_abc123def",
    "qurl_site":   "https://r_abc123xyz.qurl.site",
    "expires_at":  "2026-12-31T23:59:59Z"
  }
}
```

---

## 4. Environment Variables

### Qurl Bot

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Conditional | Bot OAuth token (`xoxb-...`), required for Slack |
| `SLACK_APP_TOKEN` | Conditional | App-level token (`xapp-...`) for Socket Mode, required for Slack |
| `DISCORD_TOKEN` | Conditional | Discord bot token, required for Discord |
| `ATLASCLOUD_API_KEY` | Yes | API key for Atlas Cloud relay LLM access (URL extraction & intent detection) |
| `LAYERV_API_URL` | No | LayerV API base URL (default: `https://api.layerv.xyz`) |
| `LAYERV_API_KEY` | No | Global LayerV API key used by Slack (shared across all users) |
| `LAYERV_STATS_URL` | No | QURL dashboard URL, returned when user asks for stats/dashboard |
| `QURL_DEFAULT_EXPIRES_IN` | No | Default QURL expiry duration (default: `30m`) |
| `ENCRYPTION_SECRET` | No | Secret for encrypting stored API keys (default provided, change in production) |

> At least one platform must be configured: `SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN` for Slack, or `DISCORD_TOKEN` for Discord. Both can be configured simultaneously.

### LayerV Backend

| Variable | Description |
|---|---|
| `PORT` | HTTP port for the QURL service (default: `3000`) |

---

## 5. Platform Configuration

### 5.1 Slack App Configuration

In your Slack app settings at https://api.slack.com/apps:

1. **OAuth & Permissions → Bot Token Scopes:** add `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write`, `users:read`, `users:read.email` (optional), `commands`
2. **Event Subscriptions:** enable and subscribe to bot events: `app_mention`, `message.im`, `app_home_opened`
3. **Socket Mode:** enable Socket Mode and generate an App-Level Token with `connections:write` scope
4. **Slash Commands:** register `/setkey`, `/mykey`, `/delkey`
5. **Install App** to workspace to obtain `xoxb-` Bot Token

> Socket Mode is used — no public URL or Request URL is needed.

### 5.2 Discord Bot Configuration

In the Discord Developer Portal at https://discord.com/developers/applications:

1. **Create Application** and add a Bot user
2. **Bot → Privileged Gateway Intents:** enable `Message Content Intent`
3. **Bot → Token:** copy the bot token for `DISCORD_TOKEN`
4. **OAuth2 → URL Generator:** select scopes `bot` + `applications.commands`; select bot permissions: `Send Messages`, `Read Message History`, `View Channel`
5. **Invite the bot** to your server using the generated URL

---

## 6. Services Detail

### 6.1 AI Analyzer (`services/ai_analyzer.py`)

Uses an Atlas Cloud hosted chat completion model to analyze user messages. The system prompt instructs the LLM to:

- Detect language (English/Chinese)
- Extract URLs from natural language, including website names (e.g., "Google" → `https://google.com`)
- Determine proxy intent (defaults to `true` if any website is mentioned)
- Parse validity period if specified

Includes robust JSON extraction from responses that may contain markdown fences or extra text.

Custom domain aliases from `domain_aliases.json` are injected into the prompt and also post-processed as a fallback.

### 6.2 LayerV Client (`services/layerv.py`)

Async HTTP client for the LayerV QURL API:

- `create_qurl()` — creates a new QURL with target URL, expiry, and description
- `verify_api_key()` — validates an API key by calling the quota endpoint
- Handles error responses: `201` success, `401` invalid key, others with graceful JSON/text fallback

### 6.3 URL Parser (`services/url_parser.py`)

Regex-based URL extraction and normalization:

- Extracts Slack-formatted links (`<url|display>`)
- Extracts full URLs (`https://...`) and bare domains (`google.com`)
- Normalizes URLs: adds `https://`, lowercases domain, adds `www.` prefix for bare domains

### 6.4 Time Utilities (`services/time_utils.py`)

Timezone-aware time formatting:

- `format_utc_to_local()` — converts UTC ISO 8601 timestamps to local time with timezone label
- `format_expires_in_display()` — converts duration strings (e.g., `"30m"`) to human-readable format (e.g., "30 minutes" / "30 分钟"), used when user timezone is unavailable
- `get_timezone_from_discord_locale()` — maps Discord locale (e.g., `"zh-CN"`) to IANA timezone (e.g., `"Asia/Shanghai"`)

### 6.5 User Store (`services/user_store.py`)

Encrypted storage for per-user API keys (used by Discord):

- Keys are encrypted with Fernet (derived from `ENCRYPTION_SECRET`)
- Stored in `data/users.json`
- Supports set/get/delete/info operations
- Includes migration logic for legacy Slack user IDs (no platform prefix → `slack:` prefix)

User ID format: `{platform}:{user_id}` (e.g., `discord:123456789`)

### 6.6 Internationalization (`services/i18n.py`)

Full bilingual support (Chinese `zh` / English `en`) for all bot messages:

- Error messages, success messages, command responses
- Welcome page (Slack App Home)
- DM delivery notifications
- Dashboard shortcut responses

Language is auto-detected by the LLM from the user's message, or inferred from CJK character presence.

### 6.7 Domain Resolver (`services/domain_resolver.py`)

Resolves custom domain aliases (e.g., internal company URLs) defined in `domain_aliases.json`:

```json
{
  "CRM": "https://crm.mycompany.com",
  "Wiki": "https://wiki.internal.example.com"
}
```

Aliases are injected into the LLM prompt and also resolved in post-processing.

---

## 7. LayerV Backend Source Code

```javascript
// ─────────────────────────────────────────────
// LayerV Backend — Slack user verification
// Steps 4 & 5 of the workflow
// ─────────────────────────────────────────────
const express = require('express');
const app     = express();
app.use(express.json());

const SLACK_API = 'https://slack.com/api';


// ─── Entry point: POST /v1/qurl ───────────────
app.post('/v1/qurl', async (req, res) => {
  const { target_url, user_email, slack_token } = req.body;

  if (!target_url || !user_email || !slack_token) {
    return res.status(400).json({ error: 'Missing required fields' });
  }

  try {
    // ── STEPS 4 & 5: Verify the Slack user ────
    const verifiedEmail = await verifySlackUser(slack_token, user_email);

    // ── STEP 6: Generate the QURL ─────────────
    const qurlData = await generateQurl(target_url, verifiedEmail);

    return res.json({ data: qurlData });

  } catch (err) {
    console.error('Verification failed:', err.message);
    return res.status(401).json({ error: err.message });
  }
});


// ─── STEP 4: auth.test ───────────────────────
// Validates the bot token and confirms which
// Slack workspace it belongs to.
//
// STEP 5: users.lookupByEmail ─────────────────
// Confirms the email belongs to a real, active
// member of that workspace.
// ─────────────────────────────────────────────
async function verifySlackUser(slackToken, claimedEmail) {

  // Step 4 — validate the bot token
  const authRes  = await fetch(`${SLACK_API}/auth.test`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${slackToken}`,
      'Content-Type':  'application/json',
    },
  });
  const authData = await authRes.json();

  if (!authData.ok) {
    throw new Error(`Invalid Slack token: ${authData.error}`);
  }

  // Step 5 — look up the user by email
  const lookupRes  = await fetch(
    `${SLACK_API}/users.lookupByEmail?email=${encodeURIComponent(claimedEmail)}`,
    { headers: { 'Authorization': `Bearer ${slackToken}` } }
  );
  const lookupData = await lookupRes.json();

  if (!lookupData.ok) {
    throw new Error(`Slack user not found for email: ${claimedEmail} (${lookupData.error})`);
  }

  const slackUser = lookupData.user;

  if (slackUser.deleted) {
    throw new Error('Slack user account is deactivated');
  }
  if (slackUser.is_bot) {
    throw new Error('Bot accounts cannot request QURLs');
  }

  console.log(`✅ Verified Slack user: ${slackUser.real_name} <${claimedEmail}>`);
  return claimedEmail;
}


// ─── STEP 6 ──────────────────────────────────
// Generate the QURL for the verified user.
// Replace with your real QURL generation logic.
// ─────────────────────────────────────────────
async function generateQurl(targetUrl, verifiedEmail) {
  const resourceId = `r_${Math.random().toString(36).slice(2, 11)}`;
  const token      = Math.random().toString(36).slice(2, 18);
  const expiresAt  = new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString();

  return {
    resource_id: resourceId,
    qurl_link:   `https://qurl.link/${token}`,
    qurl_site:   `https://${resourceId}.qurl.site`,
    expires_at:  expiresAt,
  };
}


app.listen(3000, () => console.log('LayerV QURL service running on :3000'));
```

---

## 8. Deployment

### 8.1 Quick Start

```bash
# Clone the repository
git clone <repo-url>
cd slack-qurl-bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your tokens and API keys

# Run (Slack only)
python app.py

# Run (Slack + Discord, or Discord only)
python run.py
```

### 8.2 Production Deployment (systemd)

Use the provided `deploy.sh` script:

```bash
sudo bash deploy.sh
```

This creates a systemd service (`slack-qurl-bot.service`) that:
- Runs `python run.py` as the entry point
- Automatically restarts on failure (10s delay)
- Logs to systemd journal

Common commands:
```bash
systemctl status slack-qurl-bot     # Check status
journalctl -u slack-qurl-bot -f     # View logs
systemctl restart slack-qurl-bot    # Restart
systemctl stop slack-qurl-bot       # Stop
```

### 8.3 Error Isolation

`run.py` implements error isolation: if one platform's bot fails (e.g., Discord token invalid), the other platform continues running. Each bot runs as an independent async task. The process stays alive as long as at least one bot is running.

---

## 9. Security Notes

- **Bot token is never exposed to the user.** It travels server-to-server (Qurl Bot → LayerV backend) only.
- **Email spoofing is prevented.** LayerV independently verifies the email via `users.lookupByEmail` rather than trusting the bot's claim alone.
- **QURL links are ephemeral.** They expire automatically and cannot be replayed after the session ends.
- **Proxy links are sent via DM.** When a user requests a proxy in a channel, the actual link is delivered privately via DM, reducing exposure to other channel members.
- **API keys are encrypted at rest.** User API keys (Discord) are stored with Fernet encryption derived from `ENCRYPTION_SECRET`.
- **`users:read.email` scope** must be explicitly granted by a Slack workspace admin — it is not available by default. The bot functions without it (email is only used for logging).
- **Each mentioned user gets a unique QURL.** When multiple users are mentioned, each receives their own independent proxy link that cannot be reused by others.
