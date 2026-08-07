"""Helpers for creating and validating DroneMobile API clients."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from homeassistant.core import HomeAssistant

from drone_mobile import DroneMobileClient, MFARequiredError
from drone_mobile.auth import AuthenticationManager
from drone_mobile.const import SUPPORTED_MFA_CHALLENGES

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


def _prepare_validation_client(
    hass: HomeAssistant,
    username: str,
    password: str,
    mfa_callback: Callable[[str], str] | None = None,
) -> tuple[DroneMobileClient, TemporaryDirectory, Path, Path]:
    """Create an ephemeral validation client, copying any remembered device."""
    runtime_dir = token_directory(hass, username)
    tmp = TemporaryDirectory(prefix="drone_mobile_validate_")
    tmp_dir = Path(tmp.name)
    device_file = runtime_dir / "device.json"
    if device_file.exists():
        _secure_copy(device_file, tmp_dir / "device.json")

    client = DroneMobileClient(
        username,
        password,
        token_dir=tmp_dir,
        mfa_callback=mfa_callback,
    )
    return client, tmp, tmp_dir, runtime_dir


class PendingAuthChallenge:
    """Cognito MFA challenge kept alive across Home Assistant config-flow steps.

    The pinned drone_mobile client raises ``MFARequiredError`` without exposing
    the Cognito ``Session`` token. This object captures that challenge response
    on the validation client so the user-entered code resumes the same session
    instead of starting a second ``InitiateAuth`` (which would issue another SMS).
    """

    def __init__(
        self,
        challenge_name: str,
        client: DroneMobileClient,
        tmp: TemporaryDirectory,
        tmp_dir: Path,
        runtime_dir: Path,
        challenge_response: dict[str, Any],
    ) -> None:
        """Store a live validation client and its pending Cognito challenge."""
        self.challenge_name = challenge_name
        self._client = client
        self._tmp = tmp
        self._tmp_dir = tmp_dir
        self._runtime_dir = runtime_dir
        self._challenge_response = challenge_response
        self._closed = False

    def complete(self, mfa_code: str) -> int:
        """Resume this exact Cognito challenge with the submitted MFA code."""
        if self._closed:
            raise MFARequiredError(self.challenge_name)

        self._client.auth.mfa_callback = lambda _challenge: mfa_code
        try:
            AuthenticationManager._respond_to_mfa_challenge(
                self._client.auth, self._challenge_response
            )
            vehicle_count = len(self._client.get_vehicles())
            _promote_auth_files(self._tmp_dir, self._runtime_dir)
            return vehicle_count
        finally:
            self.close()

    def close(self) -> None:
        """Close the validation client and discard the ephemeral token directory."""
        if self._closed:
            return
        self._closed = True
        self._client.close()
        self._tmp.cleanup()


def begin_credential_validation(
    hass: HomeAssistant,
    username: str,
    password: str,
) -> int | PendingAuthChallenge:
    """Force a password login, returning a vehicle count or a pending MFA challenge.

    When Cognito requires MFA, the validation client stays open and the exact
    challenge response is returned for a later ``PendingAuthChallenge.complete``
    call. Callers must ``close()`` the pending challenge on abort.
    """
    client, tmp, tmp_dir, runtime_dir = _prepare_validation_client(
        hass, username, password
    )
    captured: dict[str, dict[str, Any]] = {}

    def _capture_challenge(challenge_response: dict[str, Any]) -> Any:
        challenge_name = challenge_response.get("ChallengeName", "")
        session = challenge_response.get("Session", "")
        if challenge_name not in SUPPORTED_MFA_CHALLENGES or not session:
            return AuthenticationManager._respond_to_mfa_challenge(
                client.auth, challenge_response
            )
        captured["response"] = challenge_response
        raise MFARequiredError(challenge_name)

    # Instance override: authenticate calls this with the Cognito challenge dict
    # only, so a plain function is enough and stays scoped to this client.
    client.auth._respond_to_mfa_challenge = _capture_challenge  # type: ignore[method-assign]

    try:
        # force_refresh skips any residual access-token reuse and requires
        # username/password authentication with the submitted credentials.
        client.auth.authenticate(force_refresh=True)
        vehicle_count = len(client.get_vehicles())
        _promote_auth_files(tmp_dir, runtime_dir)
        client.close()
        tmp.cleanup()
        return vehicle_count
    except MFARequiredError:
        challenge_response = captured.get("response")
        if challenge_response is None:
            client.close()
            tmp.cleanup()
            raise
        return PendingAuthChallenge(
            challenge_name=challenge_response["ChallengeName"],
            client=client,
            tmp=tmp,
            tmp_dir=tmp_dir,
            runtime_dir=runtime_dir,
            challenge_response=challenge_response,
        )
    except Exception:
        client.close()
        tmp.cleanup()
        raise


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

    For interactive MFA across config-flow steps, use
    ``begin_credential_validation`` instead so the Cognito session is preserved.
    """
    if mfa_callback is None:
        result = begin_credential_validation(hass, username, password)
        if isinstance(result, PendingAuthChallenge):
            result.close()
            raise MFARequiredError(result.challenge_name)
        return result

    client, tmp, tmp_dir, runtime_dir = _prepare_validation_client(
        hass, username, password, mfa_callback
    )
    try:
        client.auth.authenticate(force_refresh=True)
        vehicle_count = len(client.get_vehicles())
        _promote_auth_files(tmp_dir, runtime_dir)
        return vehicle_count
    finally:
        client.close()
        tmp.cleanup()
