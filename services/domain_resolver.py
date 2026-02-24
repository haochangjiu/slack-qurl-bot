"""Custom domain alias resolver."""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Path to domain aliases config file
ALIASES_FILE = Path(__file__).parent.parent / "domain_aliases.json"


class DomainResolver:
    """Resolve custom domain aliases to full URLs."""

    def __init__(self):
        self.aliases: dict[str, str] = {}
        self.load_aliases()

    def load_aliases(self):
        """Load domain aliases from config file."""
        if ALIASES_FILE.exists():
            try:
                with open(ALIASES_FILE, "r", encoding="utf-8") as f:
                    self.aliases = json.load(f)
                logger.info(f"Loaded {len(self.aliases)} domain aliases")
            except Exception as e:
                logger.error(f"Failed to load domain aliases: {e}")
                self.aliases = {}
        else:
            logger.warning(f"Domain aliases file not found: {ALIASES_FILE}")

    def resolve(self, name: str) -> str | None:
        """
        Resolve a domain alias to its full URL.

        Args:
            name: The alias name (case-insensitive)

        Returns:
            The full URL if alias exists, None otherwise
        """
        # Case-insensitive lookup
        name_lower = name.lower()
        for alias, url in self.aliases.items():
            if alias.lower() == name_lower:
                return url
        return None

    def get_aliases_prompt(self) -> str:
        """
        Get a formatted string of aliases for AI prompt.

        Returns:
            Formatted string of alias mappings
        """
        if not self.aliases:
            return ""

        lines = ["Custom internal domain aliases (use these exact URLs):"]
        for alias, url in self.aliases.items():
            lines.append(f'  - "{alias}" → "{url}"')
        return "\n".join(lines)


# Singleton instance
domain_resolver = DomainResolver()
