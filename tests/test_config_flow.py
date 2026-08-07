"""Tests for the DroneMobile config flow forms."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from drone_mobile import AuthenticationError, InvalidCredentialsError
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from custom_components.drone_mobile.api import (
    PendingAuthChallenge,
    begin_credential_validation,
    token_directory,
    validate_credentials,
)
from custom_components.drone_mobile.config_flow import DroneMobileConfigFlow
from custom_components.drone_mobile.const import CONF_MFA_CODE


def _hass(tmp_path: Path) -> MagicMock:
    """Build a hass stub used by config-flow credential validation."""
    hass = MagicMock()
    hass.config.path.side_effect = lambda *parts: str(tmp_path.joinpath(*parts))

    async def async_add_executor_job(func, *args):
        return func(*args)

    hass.async_add_executor_job = async_add_executor_job
    return hass


def _challenge_response(
    challenge_name: str, session: str = "cognito-session"
) -> dict[str, Any]:
    """Build a Cognito MFA challenge payload."""
    params: dict[str, str] = {"USER_ID_FOR_SRP": "user-sub"}
    if challenge_name == "SMS_MFA":
        params["CODE_DELIVERY_DESTINATION"] = "+*******1234"
    return {
        "ChallengeName": challenge_name,
        "Session": session,
        "ChallengeParameters": params,
    }


def _mock_client_with_challenge(challenge: dict[str, Any]) -> MagicMock:
    """Create a client whose authenticate() surfaces a Cognito MFA challenge."""
    client = MagicMock()
    client.get_vehicles.return_value = [object()]

    def _authenticate(*, force_refresh: bool) -> object:
        assert force_refresh is True
        # Call whatever is currently bound on the instance (the capture hook).
        return client.auth._respond_to_mfa_challenge(challenge)

    client.auth.authenticate.side_effect = _authenticate
    return client


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
    client.close.assert_called()


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


def test_flow_begin_validation_uses_forced_login(tmp_path: Path) -> None:
    """The flow helper delegates to the forced-login validation path."""
    hass = _hass(tmp_path)
    flow = DroneMobileConfigFlow()
    flow.hass = hass

    with patch(
        "custom_components.drone_mobile.config_flow.begin_credential_validation",
        return_value=1,
    ) as begin:
        assert flow._begin_validation("user@example.com", "secret") == 1

    begin.assert_called_once_with(hass, "user@example.com", "secret")


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


def test_sms_mfa_preserves_cognito_session(tmp_path: Path) -> None:
    """SMS MFA must resume the original Cognito session instead of re-authing."""
    hass = _hass(tmp_path)
    flow = DroneMobileConfigFlow()
    flow.hass = hass
    challenge = _challenge_response("SMS_MFA", session="sms-session-1")

    with patch("custom_components.drone_mobile.api.DroneMobileClient") as client_cls:
        client = _mock_client_with_challenge(challenge)
        client_cls.return_value = client

        async def _run() -> dict:
            with (
                patch.object(flow, "async_set_unique_id", return_value=None),
                patch.object(flow, "_abort_if_unique_id_configured"),
            ):
                first = await flow.async_step_user(
                    {
                        CONF_USERNAME: "user@example.com",
                        CONF_PASSWORD: "secret",
                    }
                )
                assert first["type"] == "form"
                assert first["step_id"] == "mfa"
                assert first["description_placeholders"]["challenge"] == "SMS_MFA"
                assert flow._pending_mfa is not None
                assert client.auth.authenticate.call_count == 1

                with patch(
                    "custom_components.drone_mobile.api.AuthenticationManager._respond_to_mfa_challenge",
                    return_value=object(),
                ) as respond:
                    result = await flow.async_step_mfa({CONF_MFA_CODE: "123456"})

                respond.assert_called_once_with(client.auth, challenge)
                assert client.auth.mfa_callback("SMS_MFA") == "123456"
                return result

        result = asyncio.run(_run())

    assert result["type"] == "create_entry"
    assert client.auth.authenticate.call_count == 1
    assert flow._pending_mfa is None
    client.close.assert_called()


def test_authenticator_mfa_preserves_cognito_session(tmp_path: Path) -> None:
    """Authenticator MFA resumes the same SOFTWARE_TOKEN_MFA challenge session."""
    hass = _hass(tmp_path)
    challenge = _challenge_response("SOFTWARE_TOKEN_MFA", session="totp-session")

    with patch("custom_components.drone_mobile.api.DroneMobileClient") as client_cls:
        client = _mock_client_with_challenge(challenge)
        client_cls.return_value = client

        pending = begin_credential_validation(hass, "user@example.com", "secret")
        assert isinstance(pending, PendingAuthChallenge)
        assert pending.challenge_name == "SOFTWARE_TOKEN_MFA"

        with patch(
            "custom_components.drone_mobile.api.AuthenticationManager._respond_to_mfa_challenge",
            return_value=object(),
        ) as respond:
            assert pending.complete("654321") == 1

        respond.assert_called_once_with(client.auth, challenge)
        assert client.auth.mfa_callback("SOFTWARE_TOKEN_MFA") == "654321"
        assert client.auth.authenticate.call_count == 1


def test_wrong_mfa_code_restarts_challenge(tmp_path: Path) -> None:
    """A wrong MFA code closes the old session and starts a fresh challenge."""
    hass = _hass(tmp_path)
    flow = DroneMobileConfigFlow()
    flow.hass = hass
    first_challenge = _challenge_response("SMS_MFA", session="session-a")
    second_challenge = _challenge_response("SMS_MFA", session="session-b")

    with patch("custom_components.drone_mobile.api.DroneMobileClient") as client_cls:
        clients: list[MagicMock] = []

        def _factory(*_args, **_kwargs):
            challenge = first_challenge if not clients else second_challenge
            client = _mock_client_with_challenge(challenge)
            clients.append(client)
            return client

        client_cls.side_effect = _factory

        async def _run() -> dict:
            with (
                patch.object(flow, "async_set_unique_id", return_value=None),
                patch.object(flow, "_abort_if_unique_id_configured"),
            ):
                first = await flow.async_step_user(
                    {
                        CONF_USERNAME: "user@example.com",
                        CONF_PASSWORD: "secret",
                    }
                )
                assert first["step_id"] == "mfa"
                first_pending = flow._pending_mfa
                assert first_pending is not None
                assert first_pending._challenge_response["Session"] == "session-a"

                with patch(
                    "custom_components.drone_mobile.api.AuthenticationManager._respond_to_mfa_challenge",
                    side_effect=AuthenticationError(
                        "Incorrect MFA code. Please try again."
                    ),
                ):
                    retry = await flow.async_step_mfa({CONF_MFA_CODE: "000000"})

                assert retry["type"] == "form"
                assert retry["step_id"] == "mfa"
                assert retry["errors"] == {"base": "invalid_mfa"}
                assert flow._pending_mfa is not None
                assert flow._pending_mfa is not first_pending
                assert flow._pending_mfa._challenge_response["Session"] == "session-b"
                clients[0].close.assert_called()

                with patch(
                    "custom_components.drone_mobile.api.AuthenticationManager._respond_to_mfa_challenge",
                    return_value=object(),
                ) as respond:
                    result = await flow.async_step_mfa({CONF_MFA_CODE: "123456"})

                respond.assert_called_once_with(clients[1].auth, second_challenge)
                return result

        result = asyncio.run(_run())

    assert result["type"] == "create_entry"
    assert len(clients) == 2


def test_expired_mfa_code_restarts_challenge(tmp_path: Path) -> None:
    """An expired MFA code is reported and replaced with a new challenge."""
    hass = _hass(tmp_path)
    flow = DroneMobileConfigFlow()
    flow.hass = hass
    flow._credentials = {
        CONF_USERNAME: "user@example.com",
        CONF_PASSWORD: "secret",
    }

    pending = MagicMock(spec=PendingAuthChallenge)
    pending.challenge_name = "SMS_MFA"
    pending.complete.side_effect = AuthenticationError(
        "MFA code has expired. Please request a new one."
    )
    flow._pending_mfa = pending
    flow._mfa_challenge = "SMS_MFA"

    replacement = MagicMock(spec=PendingAuthChallenge)
    replacement.challenge_name = "SMS_MFA"

    with patch(
        "custom_components.drone_mobile.config_flow.begin_credential_validation",
        return_value=replacement,
    ) as begin:
        result = asyncio.run(flow.async_step_mfa({CONF_MFA_CODE: "123456"}))

    assert result["type"] == "form"
    assert result["step_id"] == "mfa"
    assert result["errors"] == {"base": "invalid_mfa"}
    pending.complete.assert_called_once_with("123456")
    begin.assert_called_once_with(hass, "user@example.com", "secret")
    assert flow._pending_mfa is replacement


def test_async_remove_closes_pending_mfa(tmp_path: Path) -> None:
    """Dismissing the flow must close the live Cognito challenge client."""
    flow = DroneMobileConfigFlow()
    flow.hass = _hass(tmp_path)
    pending = MagicMock(spec=PendingAuthChallenge)
    flow._pending_mfa = pending

    flow.async_remove()

    pending.close.assert_called_once()
    assert flow._pending_mfa is None
