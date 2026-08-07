"""Config flow for DroneMobile."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from drone_mobile import (
    AuthenticationError,
    DroneMobileException,
    NetworkError,
)

from .api import PendingAuthChallenge, begin_credential_validation
from .const import CONF_MFA_CODE, DOMAIN


class DroneMobileConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a DroneMobile config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._credentials: dict[str, str] | None = None
        self._mfa_challenge: str | None = None
        self._pending_mfa: PendingAuthChallenge | None = None
        self._reauth_entry: ConfigEntry | None = None

    @callback
    def async_remove(self) -> None:
        """Close any live MFA challenge when the flow is dismissed."""
        self._close_pending_mfa()

    def _close_pending_mfa(self) -> None:
        """Discard a pending Cognito MFA session if one is open."""
        if self._pending_mfa is not None:
            self._pending_mfa.close()
            self._pending_mfa = None

    def _finish_flow(self) -> FlowResult:
        """Create a new entry or update the entry being reauthenticated."""
        self._close_pending_mfa()
        if self._credentials is None:
            return self.async_abort(reason="reauth_entry_missing")
        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data_updates=self._credentials,
            )
        return self.async_create_entry(
            title=self._credentials[CONF_USERNAME],
            data=self._credentials,
        )

    def _begin_validation(
        self, username: str, password: str
    ) -> int | PendingAuthChallenge:
        """Start forced-password validation, maybe returning a pending MFA session."""
        self._close_pending_mfa()
        return begin_credential_validation(self.hass, username, password)

    def _complete_mfa(self, mfa_code: str) -> int:
        """Resume the stored Cognito challenge with the user-entered code."""
        if self._pending_mfa is None:
            raise AuthenticationError("MFA challenge session is closed")
        pending = self._pending_mfa
        self._pending_mfa = None
        return pending.complete(mfa_code)

    def _store_pending_mfa(self, pending: PendingAuthChallenge) -> None:
        """Keep the live Cognito challenge in flow memory for the MFA step."""
        self._pending_mfa = pending
        self._mfa_challenge = pending.challenge_name

    async def _async_restart_mfa_challenge(self) -> None:
        """Start a fresh Cognito challenge after a wrong or expired MFA code."""
        if self._credentials is None:
            return
        result = await self.hass.async_add_executor_job(
            self._begin_validation,
            self._credentials[CONF_USERNAME],
            self._credentials[CONF_PASSWORD],
        )
        if isinstance(result, PendingAuthChallenge):
            self._store_pending_mfa(result)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial credentials step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip().lower()
            password = user_input[CONF_PASSWORD]
            await self.async_set_unique_id(username)
            self._abort_if_unique_id_configured()

            try:
                result = await self.hass.async_add_executor_job(
                    self._begin_validation,
                    username,
                    password,
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except NetworkError:
                errors["base"] = "cannot_connect"
            except DroneMobileException:
                errors["base"] = "unknown"
            except Exception:
                errors["base"] = "unknown"
            else:
                self._credentials = {
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                }
                if isinstance(result, PendingAuthChallenge):
                    self._store_pending_mfa(result)
                    return await self.async_step_mfa()
                return self._finish_flow()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_mfa(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a DroneMobile MFA challenge."""
        if self._credentials is None or self._pending_mfa is None:
            self._close_pending_mfa()
            return self.async_abort(reason="mfa_session_expired")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self.hass.async_add_executor_job(
                    self._complete_mfa,
                    user_input[CONF_MFA_CODE].strip(),
                )
            except AuthenticationError:
                # Wrong/expired codes close the Cognito session. Start a new
                # challenge so SMS users receive a fresh code before retrying.
                errors["base"] = "invalid_mfa"
                try:
                    await self._async_restart_mfa_challenge()
                except Exception:
                    self._close_pending_mfa()
                    return self.async_abort(reason="mfa_session_expired")
                if self._pending_mfa is None:
                    return self._finish_flow()
            except Exception:
                self._close_pending_mfa()
                return self.async_abort(reason="mfa_session_expired")
            else:
                return self._finish_flow()

        return self.async_show_form(
            step_id="mfa",
            data_schema=vol.Schema({vol.Required(CONF_MFA_CODE): str}),
            description_placeholders={
                "challenge": self._mfa_challenge or "MFA",
            },
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Start reauthentication for an existing account."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        if self._reauth_entry is None:
            return self.async_abort(reason="reauth_entry_missing")
        self._credentials = {
            CONF_USERNAME: entry_data[CONF_USERNAME],
            CONF_PASSWORD: entry_data[CONF_PASSWORD],
        }
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect and validate a new password."""
        if self._credentials is None:
            return self.async_abort(reason="reauth_entry_missing")

        errors: dict[str, str] = {}
        if user_input is not None:
            self._credentials[CONF_PASSWORD] = user_input[CONF_PASSWORD]
            try:
                result = await self.hass.async_add_executor_job(
                    self._begin_validation,
                    self._credentials[CONF_USERNAME],
                    self._credentials[CONF_PASSWORD],
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except NetworkError:
                errors["base"] = "cannot_connect"
            except DroneMobileException:
                errors["base"] = "unknown"
            except Exception:
                errors["base"] = "unknown"
            else:
                if isinstance(result, PendingAuthChallenge):
                    self._store_pending_mfa(result)
                    return await self.async_step_mfa()
                return self._finish_flow()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={
                "username": self._credentials[CONF_USERNAME],
            },
            errors=errors,
        )
