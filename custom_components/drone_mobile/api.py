"""Helpers for creating and validating DroneMobile API clients."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

from homeassistant.core import HomeAssistant

from drone_mobile import DroneMobileClient

from .const import DOMAIN


def token_directory(hass: HomeAssistant, username: str) -> Path:
    """Return an account-specific token directory inside Home Assistant storage."""
    account_id = sha256(username.strip().lower().encode()).hexdigest()[:16]
    return Path(hass.config.path(".storage", DOMAIN, account_id))


def create_client(
    hass: HomeAssistant,
    username: str,
    password: str,
    mfa_callback: Callable[[str], str] | None = None,
) -> DroneMobileClient:
    """Create a DroneMobile client with isolated persistent token storage."""
    return DroneMobileClient(
        username,
        password,
        token_dir=token_directory(hass, username),
        mfa_callback=mfa_callback,
    )
