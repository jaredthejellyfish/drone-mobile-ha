"""Tests for the DroneMobile config flow forms."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

from drone_mobile import AuthenticationError, InvalidCredentialsError
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from custom_components.drone_mobile.api import token_directory, validate_credentials
from custom_components.drone_mobile.config_flow import DroneMobileConfigFlow


def _hass(tmp_path: Path) -> MagicMock:
    """Build a hass stub used by config-flow credential validation."""
    hass = MagicMock()
    hass.config.path.side_effect = lambda *parts: str(tmp_path.joinpath(*parts))

    async def async_add_executor_job(func, *args):
        return func(*args)

    hass.async_add_executor_job = async_add_executor_job
    return hass


def test_initial_form() -> None:
    """The flow starts with the account credentials form."""
    result = asyncio.run(DroneMobileConfigFlow().async_step_user())

    assert result["type"] == "form"
    assert result["step_id"] == "user"


def test_mfa_without_credentials_aborts() -> None:
    """A stale MFA step cannot create a partial config entry."""
    result = asyncio.run(DroneMobileConfigFlow().async_step_mfa())

    assert result["type"] == "abort"
    assert result["reason"] == "mfa_session_expired"


def test_setup_rejects_wrong_password_with_cached_token(tmp_path: Path) -> None:
    """Setup must reject a wrong password even when a cached token is valid."""
    hass = _hass(tmp_path)
    username = "user@example.com"
    runtime_dir = token_directory(hass, username)
    runtime_dir.mkdir(parents=True)
    cached_token = runtime_dir / "token.json"
    cached_token.write_text('{"id_token":"still-valid","token_type":"Bearer"}')
    original = cached_token.read_text()

    flow = DroneMobileConfigFlow()
    flow.hass = hass

    with patch("custom_components.drone_mobile.api.DroneMobileClient") as client_cls:
        client = client_cls.return_value
        client.auth.authenticate.side_effect = InvalidCredentialsError(
            "Invalid username or password"
        )

        async def _run() -> dict:
            with (
                patch.object(flow, "async_set_unique_id", return_value=None),
                patch.object(flow, "_abort_if_unique_id_configured"),
            ):
                return await flow.async_step_user(
                    {
                        CONF_USERNAME: username,
                        CONF_PASSWORD: "wrong-password",
                    }
                )

        result = asyncio.run(_run())

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}
    assert cached_token.read_text() == original
    client.auth.authenticate.assert_called_once_with(force_refresh=True)


def test_reauth_rejects_wrong_password_with_cached_token(tmp_path: Path) -> None:
    """Reauthentication must reject a wrong password despite a cached token."""
    hass = _hass(tmp_path)
    username = "user@example.com"
    runtime_dir = token_directory(hass, username)
    runtime_dir.mkdir(parents=True)
    cached_token = runtime_dir / "token.json"
    cached_token.write_text('{"id_token":"still-valid","token_type":"Bearer"}')
    original = cached_token.read_text()

    flow = DroneMobileConfigFlow()
    flow.hass = hass
    flow._reauth_entry = MagicMock()
    flow._credentials = {
        CONF_USERNAME: username,
        CONF_PASSWORD: "old-password",
    }

    with patch("custom_components.drone_mobile.api.DroneMobileClient") as client_cls:
        client = client_cls.return_value
        client.auth.authenticate.side_effect = InvalidCredentialsError(
            "Invalid username or password"
        )

        result = asyncio.run(
            flow.async_step_reauth_confirm({CONF_PASSWORD: "wrong-password"})
        )

    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}
    assert flow._credentials[CONF_PASSWORD] == "wrong-password"
    assert cached_token.read_text() == original
    client.auth.authenticate.assert_called_once_with(force_refresh=True)


def test_flow_validate_credentials_uses_forced_login(tmp_path: Path) -> None:
    """The flow helper delegates to the forced-login validation path."""
    hass = _hass(tmp_path)
    flow = DroneMobileConfigFlow()
    flow.hass = hass

    with patch(
        "custom_components.drone_mobile.config_flow.validate_credentials",
        return_value=1,
    ) as validate:
        assert flow._validate_credentials("user@example.com", "secret") == 1

    validate.assert_called_once_with(hass, "user@example.com", "secret", None)


def test_cached_token_alone_is_insufficient_for_validation(tmp_path: Path) -> None:
    """validate_credentials must not succeed from a cached token without login."""
    hass = _hass(tmp_path)
    username = "user@example.com"
    runtime_dir = token_directory(hass, username)
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "token.json").write_text('{"id_token":"still-valid"}')

    with patch("custom_components.drone_mobile.api.DroneMobileClient") as client_cls:
        client = client_cls.return_value
        # Mimic the old bug: get_vehicles would succeed via the cached token,
        # but forced authentication correctly rejects the password.
        client.get_vehicles.return_value = [object()]
        client.auth.authenticate.side_effect = AuthenticationError("bad password")

        try:
            validate_credentials(hass, username, "wrong-password")
            raised = False
        except AuthenticationError:
            raised = True

    assert raised
    client.get_vehicles.assert_not_called()
