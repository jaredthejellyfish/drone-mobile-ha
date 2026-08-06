"""Tests for DroneMobile integration API helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from custom_components.drone_mobile.api import token_directory


def test_token_directory_is_stable_and_account_specific() -> None:
    """Credentials for separate accounts cannot overwrite one another."""
    hass = MagicMock()
    hass.config.path.side_effect = lambda *parts: "/config/" + "/".join(parts)

    first = token_directory(hass, "USER@example.com ")
    same = token_directory(hass, "user@example.com")
    second = token_directory(hass, "other@example.com")

    assert first == same
    assert first != second
    assert first.parent == Path("/config/.storage/drone_mobile")
    assert "user@example.com" not in str(first)
