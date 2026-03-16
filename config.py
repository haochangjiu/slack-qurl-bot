from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Slack (optional - omit to run Discord-only)
    slack_bot_token: str | None = None
    slack_app_token: str | None = None

    # Discord (optional - omit to run Slack-only)
    discord_token: str | None = None

    # Claude API
    anthropic_api_key: str

    # LayerV API
    layerv_api_url: str = "https://api.layerv.xyz"
    layerv_api_key: str | None = None
    layerv_stats_url: str | None = None

    # QURL defaults
    qurl_default_expires_in: str = "30m"

    # Encryption secret for storing user API keys
    encryption_secret: str = "slack-qurl-bot-default-secret"

    class Config:
        env_file = ".env"


settings = Settings()
