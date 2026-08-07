"""Constants for the DroneMobile integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "drone_mobile"

CONF_MFA_CODE = "mfa_code"

DEFAULT_UPDATE_INTERVAL = timedelta(minutes=2)
COMMAND_REFRESH_RETRY_INTERVALS = (5, 10, 15)
LOCATION_UPDATE_INTERVAL = timedelta(minutes=5)
PARKED_LOCATION_UPDATE_INTERVAL = timedelta(minutes=30)
LOCATION_REFRESH_DELAY = 15

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.LOCK,
    Platform.SENSOR,
    Platform.SWITCH,
]
