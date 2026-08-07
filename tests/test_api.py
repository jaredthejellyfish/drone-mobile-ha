"""Tests for DroneMobile integration API helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from drone_mobile import InvalidCredentialsError

from custom_components.drone_mobile.api import (
    PendingAuthChallenge,
    begin_credential_validation,
    create_client,
    token_directory,
    validate_credentials,
)


def _hass(tmp_path: Path) -> MagicMock:
    """Build a hass stub that stores tokens under tmp_path."""
    hass = MagicMock()
    hass.config.path.side_effect = lambda *parts: str(tmp_path.joinpath(*parts))
    return hass


def test_token_directory_is_stable_and_account_specific(tmp_path: Path) -> None:
    """Credentials for separate accounts cannot overwrite one another."""
    hass = _hass(tmp_path)

    first = token_directory(hass, "USER@example.com ")
    same = token_directory(hass, "user@example.com")
    second = token_directory(hass, "other@example.com")

    assert first == same
    assert first != second
    assert first.parent == tmp_path / ".storage" / "drone_mobile"
    assert "user@example.com" not in str(first)


def test_validate_credentials_rejects_wrong_password_with_cached_token(
    tmp_path: Path,
) -> None:
    """A still-valid cached token must not make a wrong password succeed."""
    hass = _hass(tmp_path)
    username = "user@example.com"
    runtime_dir = token_directory(hass, username)
    runtime_dir.mkdir(parents=True)
    cached_token = runtime_dir / "token.json"
    cached_token.write_text('{"id_token":"still-valid","token_type":"Bearer"}')
    original = cached_token.read_text()

    with patch("custom_components.drone_mobile.api.DroneMobileClient") as client_cls:
        client = MagicMock()
        client.auth.authenticate.side_effect = InvalidCredentialsError(
            "Invalid username or password"
        )
        client_cls.return_value = client

        with pytest.raises(InvalidCredentialsError):
            validate_credentials(hass, username, "wrong-password")

        client.auth.authenticate.assert_called_once_with(force_refresh=True)
        client.get_vehicles.assert_not_called()
        client.close.assert_called_once()

        token_dir = client_cls.call_args.kwargs["token_dir"]
        assert token_dir != runtime_dir
        assert cached_token.read_text() == original


def test_validate_credentials_promotes_tokens_on_success(tmp_path: Path) -> None:
    """Successful forced login replaces the account's runtime auth files."""
    hass = _hass(tmp_path)
    username = "user@example.com"
    runtime_dir = token_directory(hass, username)
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "token.json").write_text('{"id_token":"old"}')
    (runtime_dir / "device.json").write_text('{"DeviceKey":"remembered"}')

    captured: dict[str, object] = {}

    with patch("custom_components.drone_mobile.api.DroneMobileClient") as client_cls:
        client = MagicMock()
        client.get_vehicles.return_value = [object(), object()]

        def _client_factory(*_args, **kwargs):
            token_dir = kwargs["token_dir"]
            captured["token_dir"] = token_dir
            captured["had_device"] = (token_dir / "device.json").exists()
            if captured["had_device"]:
                captured["device"] = (token_dir / "device.json").read_text()
            return client

        def _authenticate(*, force_refresh: bool) -> object:
            assert force_refresh is True
            token_dir = captured["token_dir"]
            assert isinstance(token_dir, Path)
            (token_dir / "token.json").write_text('{"id_token":"fresh"}')
            (token_dir / "device.json").write_text('{"DeviceKey":"new-device"}')
            return object()

        client_cls.side_effect = _client_factory
        client.auth.authenticate.side_effect = _authenticate

        assert validate_credentials(hass, username, "correct-password") == 2

        assert captured["had_device"] is True
        assert captured["device"] == '{"DeviceKey":"remembered"}'
        assert captured["token_dir"] != runtime_dir
        assert (runtime_dir / "token.json").read_text() == '{"id_token":"fresh"}'
        assert (runtime_dir / "device.json").read_text() == '{"DeviceKey":"new-device"}'
        client.close.assert_called_once()


def test_create_client_uses_account_token_directory(tmp_path: Path) -> None:
    """Runtime clients keep using the persistent account token directory."""
    hass = _hass(tmp_path)

    with patch("custom_components.drone_mobile.api.DroneMobileClient") as client_cls:
        create_client(hass, "user@example.com", "secret")

    assert client_cls.call_args.kwargs["token_dir"] == token_directory(
        hass, "user@example.com"
    )


def test_begin_credential_validation_returns_pending_mfa_challenge(
    tmp_path: Path,
) -> None:
    """MFA challenges keep the validation client open with the Cognito session."""
    hass = _hass(tmp_path)
    challenge = {
        "ChallengeName": "SMS_MFA",
        "Session": "live-session",
        "ChallengeParameters": {"CODE_DELIVERY_DESTINATION": "+*******9999"},
    }

    with patch("custom_components.drone_mobile.api.DroneMobileClient") as client_cls:
        client = MagicMock()

        def _authenticate(*, force_refresh: bool) -> object:
            return client.auth._respond_to_mfa_challenge(challenge)

        client.auth.authenticate.side_effect = _authenticate
        client_cls.return_value = client

        pending = begin_credential_validation(hass, "user@example.com", "secret")

        assert isinstance(pending, PendingAuthChallenge)
        assert pending.challenge_name == "SMS_MFA"
        assert pending._challenge_response["Session"] == "live-session"
        client.close.assert_not_called()

        with patch(
            "custom_components.drone_mobile.api.AuthenticationManager._respond_to_mfa_challenge",
            return_value=object(),
        ) as respond:
            client.get_vehicles.return_value = [object(), object()]
            assert pending.complete("123456") == 2

        respond.assert_called_once_with(client.auth, challenge)
        client.close.assert_called_once()
