"""
Backward-compatible entry for Slack-only mode.
Use run.py to run Slack and/or Discord based on configuration.
"""

import asyncio
import sys

from config import settings

if __name__ == "__main__":
    if not (settings.slack_bot_token and settings.slack_app_token):
        print("Slack tokens not configured. Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN.")
        print("For Slack + Discord, use: python run.py")
        sys.exit(1)
    from adapters.slack_app import run_slack
    asyncio.run(run_slack())
