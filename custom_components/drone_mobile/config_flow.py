"""Config flow for DroneMobile."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult

from drone_mobile import (
    AuthenticationError,
    DroneMobileException,
    MFARequiredError,
    NetworkError,
)

from .api import validate_credentials
from .const import CONF_MFA_CODE, DOMAIN


class DroneMobileConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a DroneMobile config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._credentials: dict[str, str] | None = None
        self._mfa_challenge: str | None = None
        self._reauth_entry: ConfigEntry | None = None

    def _finish_flow(self) -> FlowResult:
        """Create a new entry or update the entry being reauthenticated."""
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

    def _validate_credentials(
        self,
        username: str,
        password: str,
        mfa_code: str | None = None,
    ) -> int:
        """Validate credentials with a forced password login."""
        callback = (lambda _challenge: mfa_code) if mfa_code is not None else None
        return validate_credentials(self.hass, username, password, callback)

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
                await self.hass.async_add_executor_job(
                    self._validate_credentials,
                    username,
                    password,
                )
            except MFARequiredError as err:
                self._credentials = {
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                }
                self._mfa_challenge = err.challenge_name
                return await self.async_step_mfa()
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
        if self._credentials is None:
            return self.async_abort(reason="mfa_session_expired")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self.hass.async_add_executor_job(
                    self._validate_credentials,
                    self._credentials[CONF_USERNAME],
                    self._credentials[CONF_PASSWORD],
                    user_input[CONF_MFA_CODE].strip(),
                )
            except AuthenticationError:
                errors["base"] = "invalid_mfa"
            except NetworkError:
                errors["base"] = "cannot_connect"
            except DroneMobileException:
                errors["base"] = "unknown"
            except Exception:
                errors["base"] = "unknown"
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
                await self.hass.async_add_executor_job(
                    self._validate_credentials,
                    self._credentials[CONF_USERNAME],
                    self._credentials[CONF_PASSWORD],
                )
            except MFARequiredError as err:
                self._mfa_challenge = err.challenge_name
                return await self.async_step_mfa()
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except NetworkError:
                errors["base"] = "cannot_connect"
            except DroneMobileException:
                errors["base"] = "unknown"
            except Exception:
                errors["base"] = "unknown"
            else:
                return self._finish_flow()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={
                "username": self._credentials[CONF_USERNAME],
            },
            errors=errors,
        )
