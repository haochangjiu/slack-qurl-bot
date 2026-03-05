"""User API Key storage service."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from cryptography.fernet import Fernet
from base64 import urlsafe_b64encode
from hashlib import sha256

logger = logging.getLogger(__name__)

# Data file path
DATA_DIR = Path(__file__).parent.parent / "data"
USERS_FILE = DATA_DIR / "users.json"


class UserStore:
    """Store and manage user API keys."""

    def __init__(self):
        self._users: dict = {}
        self._fernet: Fernet | None = None
        self._init_encryption()
        self._load()

    def _init_encryption(self):
        """Initialize encryption key from config."""
        from config import settings
        # Derive a valid Fernet key from the secret
        key = urlsafe_b64encode(sha256(settings.encryption_secret.encode()).digest())
        self._fernet = Fernet(key)

    def _load(self):
        """Load users from file."""
        if USERS_FILE.exists():
            try:
                with open(USERS_FILE, "r", encoding="utf-8") as f:
                    self._users = json.load(f)
                logger.info(f"Loaded {len(self._users)} user records")
            except Exception as e:
                logger.error(f"Failed to load users: {e}")
                self._users = {}
        else:
            self._users = {}
            # Ensure data directory exists
            DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _save(self):
        """Save users to file."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(USERS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._users, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save users: {e}")

    def _encrypt(self, value: str) -> str:
        """Encrypt a value."""
        return self._fernet.encrypt(value.encode()).decode()

    def _decrypt(self, value: str) -> str:
        """Decrypt a value."""
        return self._fernet.decrypt(value.encode()).decode()

    def set_api_key(self, user_id: str, api_key: str) -> None:
        """
        Save user's API key.

        Args:
            user_id: Slack user ID
            api_key: LayerV API key
        """
        self._users[user_id] = {
            "api_key_encrypted": self._encrypt(api_key),
            "api_key_prefix": api_key[:8] + "..." if len(api_key) > 8 else api_key,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        self._save()
        logger.info(f"Saved API key for user {user_id}")

    def get_api_key(self, user_id: str) -> str | None:
        """
        Get user's API key.

        Args:
            user_id: Slack user ID

        Returns:
            Decrypted API key or None if not found
        """
        user = self._users.get(user_id)
        if not user:
            return None
        try:
            return self._decrypt(user["api_key_encrypted"])
        except Exception as e:
            logger.error(f"Failed to decrypt API key for {user_id}: {e}")
            return None

    def has_api_key(self, user_id: str) -> bool:
        """Check if user has an API key configured."""
        return user_id in self._users

    def get_key_info(self, user_id: str) -> dict | None:
        """
        Get user's API key info (without full key).

        Args:
            user_id: Slack user ID

        Returns:
            Dict with key prefix and created_at, or None
        """
        user = self._users.get(user_id)
        if not user:
            return None
        return {
            "api_key_prefix": user.get("api_key_prefix", "***"),
            "created_at": user.get("created_at"),
        }

    def delete_api_key(self, user_id: str) -> bool:
        """
        Delete user's API key.

        Args:
            user_id: Slack user ID

        Returns:
            True if deleted, False if not found
        """
        if user_id in self._users:
            del self._users[user_id]
            self._save()
            logger.info(f"Deleted API key for user {user_id}")
            return True
        return False


# Singleton instance
user_store = UserStore()
