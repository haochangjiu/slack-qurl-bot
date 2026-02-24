from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Slack
    slack_bot_token: str
    slack_app_token: str

    # Claude API
    anthropic_api_key: str

    # LayerV API
    layerv_api_url: str = "https://api.layerv.xyz"
    layerv_auth0_token_url: str = "https://dev-q1kiedn8knbutena.us.auth0.com/oauth/token"
    layerv_auth0_client_id: str = "lleycdz9HFP7ZnLtsk70hs5qUR8SphPI"
    layerv_auth0_client_secret: str = "XPvBPKgntudOCPe9rnKEs744ej4VGxDcsxpM80anpae-Y35lEPmUOao_i7duANDS"
    layerv_auth0_audience: str = "https://api.layerv.xyz"

    # QURL defaults
    qurl_default_expires_in: str = "24h"

    class Config:
        env_file = ".env"


settings = Settings()
