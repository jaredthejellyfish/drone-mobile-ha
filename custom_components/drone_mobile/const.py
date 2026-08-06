"""Constants for the DroneMobile integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "drone_mobile"

CONF_MFA_CODE = "mfa_code"

DEFAULT_UPDATE_INTERVAL = timedelta(minutes=2)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.LOCK,
    Platform.SENSOR,
    Platform.SWITCH,
]
