import httpx
import logging
from dataclasses import dataclass

from config import settings

logger = logging.getLogger(__name__)


class NoApiKeyError(Exception):
    """Raised when user has no API key configured."""
    pass


class InvalidApiKeyError(Exception):
    """Raised when API key is invalid."""
    pass


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

    async def verify_api_key(self, api_key: str) -> bool:
        """
        Verify if an API key is valid by making a test request.

        Args:
            api_key: LayerV API key

        Returns:
            True if valid, False otherwise
        """
        try:
            async with httpx.AsyncClient() as client:
                # Try to get quota info to verify the key
                response = await client.get(
                    f"{self.api_url}/v1/quota",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                    },
                    timeout=10.0,
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to verify API key: {e}")
            return False

    async def create_qurl(
        self,
        api_key: str,
        target_url: str,
        expires_in: str | None = None,
        description: str | None = None,
        one_time_use: bool = True,
    ) -> QURLResponse:
        """
        Create a new QURL for the target URL.

        Args:
            api_key: User's LayerV API key
            target_url: The URL to protect with QURL
            expires_in: Duration until expiration (e.g., "30m", "24h", "7d")
            description: Human-readable description
            one_time_use: Whether the QURL can only be accessed once (default True)

        Returns:
            QURLResponse with the generated qurl_link

        Raises:
            InvalidApiKeyError: If the API key is invalid
            Exception: For other API errors
        """
        payload = {
            "target_url": target_url,
            "expires_in": expires_in or settings.qurl_default_expires_in,
            "one_time_use": one_time_use,
        }
        if description:
            payload["description"] = description

        logger.info(f"Creating QURL with api_key: {api_key[:12]}..., target_url: {target_url}")
        logger.info(f"Payload: {payload}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_url}/v1/qurl",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )

            logger.info(f"QURL API response status: {response.status_code}, body: {response.text[:200]}")
            if response.status_code == 201:
                data = response.json()["data"]
                return QURLResponse(
                    resource_id=data["resource_id"],
                    qurl_link=data["qurl_link"],
                    qurl_site=data["qurl_site"],
                    expires_at=data["expires_at"],
                )
            elif response.status_code == 401:
                logger.error(f"API key invalid, response: {response.text}")
                raise InvalidApiKeyError("Invalid or expired API key")
            else:
                logger.error(f"QURL API error: {response.status_code} - {response.text}")
                error_data = response.json()
                error_detail = error_data.get("error", {}).get(
                    "detail", "Unknown error"
                )
                raise Exception(f"Failed to create QURL: {error_detail}")


# Singleton instance
layerv_client = LayerVClient()
