"""Tests for the DroneMobile config flow forms."""

from __future__ import annotations

import asyncio

from custom_components.drone_mobile.config_flow import DroneMobileConfigFlow


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
