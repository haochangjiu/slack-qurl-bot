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

    # File upload API (Discord file upload to QURL)
    upload_api_url: str | None = None  # e.g. http://localhost:8080

    # Mint link API base URL (address before /{resource_id}), e.g. https://get.qurl.link/api/mint_link
    mint_link_api_url: str = "https://get.qurl.link/api/mint_link"

    # Google Maps Embed API key (optional - enables stable embed URL generation for goo.gl short links)
    google_maps_embed_api_key: str | None = None

    # SQLite database path for resource tracking (Discord file/map upload records + mint link history)
    db_path: str = "data/resources.db"

    class Config:
        env_file = ".env"


settings = Settings()
