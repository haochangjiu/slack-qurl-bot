import httpx
from dataclasses import dataclass

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
        self.api_key = settings.layerv_api_key

    async def create_qurl(
        self,
        target_url: str,
        expires_in: str | None = None,
        description: str | None = None,
        one_time_use: bool = True,
    ) -> QURLResponse:
        """
        Create a new QURL for the target URL.

        Args:
            target_url: The URL to protect with QURL
            expires_in: Duration until expiration (e.g., "30m", "24h", "7d")
            description: Human-readable description
            one_time_use: Whether the QURL can only be accessed once (default True)

        Returns:
            QURLResponse with the generated qurl_link
        """
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
                    "Authorization": f"Bearer {self.api_key}",
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
