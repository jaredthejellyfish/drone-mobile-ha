"""Helpers for creating and validating DroneMobile API clients."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from homeassistant.core import HomeAssistant

from drone_mobile import DroneMobileClient

from .const import DOMAIN

_AUTH_FILES = ("token.json", "device.json")


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


def _secure_copy(source: Path, destination: Path) -> None:
    """Copy an auth file and tighten its permissions when possible."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass


def _promote_auth_files(source_dir: Path, destination_dir: Path) -> None:
    """Copy validated auth files into the account's runtime token directory."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(destination_dir, 0o700)
    except OSError:
        pass
    for name in _AUTH_FILES:
        source = source_dir / name
        if source.exists():
            _secure_copy(source, destination_dir / name)


def validate_credentials(
    hass: HomeAssistant,
    username: str,
    password: str,
    mfa_callback: Callable[[str], str] | None = None,
) -> int:
    """Authenticate with the submitted password, ignoring cached access tokens.

    Validation runs against an ephemeral token directory so a failed attempt
    cannot replace or delete a known-good runtime token. A remembered Cognito
    device (if present) is copied into that directory so reauthentication can
    still complete device SRP the same way runtime clients would. On success,
    the resulting auth files are promoted into the account token directory.
    """
    runtime_dir = token_directory(hass, username)
    with TemporaryDirectory(prefix="drone_mobile_validate_") as tmp:
        tmp_dir = Path(tmp)
        device_file = runtime_dir / "device.json"
        if device_file.exists():
            _secure_copy(device_file, tmp_dir / "device.json")

        client = DroneMobileClient(
            username,
            password,
            token_dir=tmp_dir,
            mfa_callback=mfa_callback,
        )
        try:
            # force_refresh skips any residual access-token reuse and requires
            # username/password authentication with the submitted credentials.
            client.auth.authenticate(force_refresh=True)
            vehicle_count = len(client.get_vehicles())
            _promote_auth_files(tmp_dir, runtime_dir)
            return vehicle_count
        finally:
            client.close()
