import httpx
from dataclasses import dataclass
from datetime import datetime, timedelta

from config import settings


@dataclass
class QURLResponse:
    resource_id: str
    qurl_link: str
    qurl_site: str
    expires_at: str


class LayerVClient:
    """Client for LayerV QURL API."""

    def __init__(self):
        self.api_url = settings.layerv_api_url
        self.token_url = settings.layerv_auth0_token_url
        self.client_id = settings.layerv_auth0_client_id
        self.client_secret = settings.layerv_auth0_client_secret
        self.audience = settings.layerv_auth0_audience
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    async def _get_access_token(self) -> str:
        """Get Auth0 access token using client credentials flow."""
        # Return cached token if still valid
        if self._token and self._token_expires_at:
            if datetime.now() < self._token_expires_at - timedelta(minutes=5):
                return self._token

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_url,
                json={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "audience": self.audience,
                    "grant_type": "client_credentials",
                },
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

            self._token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)

            return self._token

    async def create_qurl(
        self,
        target_url: str,
        expires_in: str | None = None,
        description: str | None = None,
        one_time_use: bool = False,
    ) -> QURLResponse:
        """
        Create a new QURL for the target URL.

        Args:
            target_url: The URL to protect with QURL
            expires_in: Duration until expiration (e.g., "24h", "7d")
            description: Human-readable description
            one_time_use: Whether the QURL can only be accessed once

        Returns:
            QURLResponse with the generated qurl_link
        """
        token = await self._get_access_token()

        payload = {
            "target_url": target_url,
            "expires_in": expires_in or settings.qurl_default_expires_in,
            "one_time_use": one_time_use,
        }
        if description:
            payload["description"] = description

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_url}/v1/qurl",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )

            if response.status_code == 201:
                data = response.json()["data"]
                return QURLResponse(
                    resource_id=data["resource_id"],
                    qurl_link=data["qurl_link"],
                    qurl_site=data["qurl_site"],
                    expires_at=data["expires_at"],
                )
            else:
                error_data = response.json()
                error_detail = error_data.get("error", {}).get(
                    "detail", "Unknown error"
                )
                raise Exception(f"Failed to create QURL: {error_detail}")


# Singleton instance
layerv_client = LayerVClient()
