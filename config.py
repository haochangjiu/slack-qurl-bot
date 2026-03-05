from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Slack
    slack_bot_token: str
    slack_app_token: str

    # Claude API
    anthropic_api_key: str

    # LayerV API
    layerv_api_url: str = "https://api.layerv.xyz"
    layerv_api_key: str

    # QURL defaults
    qurl_default_expires_in: str = "30m"

    class Config:
        env_file = ".env"


settings = Settings()
