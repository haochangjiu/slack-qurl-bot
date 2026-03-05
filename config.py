from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Slack
    slack_bot_token: str
    slack_app_token: str

    # Claude API
    anthropic_api_key: str

    # LayerV API
    layerv_api_url: str = "https://api.layerv.xyz"

    # QURL defaults
    qurl_default_expires_in: str = "30m"

    # Encryption secret for storing user API keys
    encryption_secret: str = "slack-qurl-bot-default-secret"

    class Config:
        env_file = ".env"


settings = Settings()
