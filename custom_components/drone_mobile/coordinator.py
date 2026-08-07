"""Data coordinator for DroneMobile vehicles."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from drone_mobile import (
    AuthenticationError,
    CommandResponse,
    DroneMobileClient,
    DroneMobileException,
    Vehicle,
    VehicleStatus,
)
from drone_mobile.const import AVAILABLE_COMMANDS, DEVICE_TYPE_CONTROLLER

from .const import (
    COMMAND_REFRESH_RETRY_INTERVALS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    LOCATION_REFRESH_DELAY,
    LOCATION_UPDATE_INTERVAL,
    PARKED_LOCATION_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

COMMAND_METHODS = frozenset(
    {
        "aux1",
        "aux2",
        "get_location",
        "lock",
        "panic_off",
        "panic_on",
        "poll_status",
        "start",
        "stop",
        "trunk",
        "unlock",
    }
)

COMMAND_EXPECTATIONS: dict[str, tuple[str, bool]] = {
    "start": ("is_running", True),
    "stop": ("is_running", False),
    "lock": ("is_locked", True),
    "unlock": ("is_locked", False),
}

LOCATION_COMMAND = "A30"


def _request_location(client: DroneMobileClient, device_key: str) -> CommandResponse:
    """Request location using the controller command expected by the API."""
    # drone_mobile 0.3+ changed this to the rejected LOCATION vehicle command.
    # A30 with the controller device type is the package's last known working
    # command syntax. Add it to the library allowlist before sending it.
    AVAILABLE_COMMANDS.add(LOCATION_COMMAND)
    return client.send_command(
        device_key,
        LOCATION_COMMAND,
        DEVICE_TYPE_CONTROLLER,
    )


@dataclass(frozen=True, slots=True)
class DroneMobileVehicleData:
    """A vehicle and its latest status."""

    vehicle: Vehicle
    status: VehicleStatus


class DroneMobileCoordinator(DataUpdateCoordinator[dict[str, DroneMobileVehicleData]]):
    """Fetch account data once for all DroneMobile entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: DroneMobileClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )
        self.client = client
        self._command_refresh_cancels: dict[str, Callable[[], None]] = {}
        self._location_update_cancel: Callable[[], None] | None = None
        self._location_refresh_cancel: Callable[[], None] | None = None
        self._last_location_request: dict[str, datetime] = {}

    def async_start_location_updates(self) -> None:
        """Request fresh GPS locations at the configured interval."""
        if self._location_update_cancel is not None:
            return
        self._location_update_cancel = async_track_time_interval(
            self.hass,
            self._async_update_locations,
            LOCATION_UPDATE_INTERVAL,
        )

    def _schedule_location_refresh(self) -> None:
        """Fetch vehicle data after a location command has propagated."""
        if self._location_refresh_cancel is not None:
            self._location_refresh_cancel()

        async def _async_refresh(_now: object) -> None:
            self._location_refresh_cancel = None
            await self.async_request_refresh()

        self._location_refresh_cancel = async_call_later(
            self.hass,
            LOCATION_REFRESH_DELAY,
            _async_refresh,
        )

    def _location_update_due(
        self,
        vehicle_id: str,
        is_running: bool,
        now: datetime,
    ) -> bool:
        """Return whether a vehicle is due for an active GPS request."""
        if is_running:
            return True
        last_request = self._last_location_request.get(vehicle_id)
        return (
            last_request is None
            or now - last_request >= PARKED_LOCATION_UPDATE_INTERVAL
        )

    async def _async_request_vehicle_location(
        self,
        vehicle_data: DroneMobileVehicleData,
        requested_at: datetime,
    ) -> bool:
        """Request one vehicle's location and record successful requests."""
        try:
            response = await self.hass.async_add_executor_job(
                _request_location,
                self.client,
                vehicle_data.vehicle.device_key,
            )
        except AuthenticationError:
            if self.config_entry:
                self.config_entry.async_start_reauth_if_available(self.hass)
            return False
        except DroneMobileException as err:
            _LOGGER.warning(
                "Unable to request location for %s: %s",
                vehicle_data.vehicle.name,
                err,
            )
            return False

        if not response.success:
            _LOGGER.warning(
                "DroneMobile rejected location request for %s: %s",
                vehicle_data.vehicle.name,
                response.message or "Unknown error",
            )
            return False

        self._last_location_request[vehicle_data.vehicle.vehicle_id] = requested_at
        return True

    async def _async_update_locations(self, now: datetime) -> None:
        """Request an updated location for every vehicle."""
        requested = False
        for vehicle_data in tuple(self.data.values()):
            if not self._location_update_due(
                vehicle_data.vehicle.vehicle_id,
                vehicle_data.status.is_running,
                now,
            ):
                continue
            requested |= await self._async_request_vehicle_location(
                vehicle_data,
                now,
            )

        if requested:
            self._schedule_location_refresh()

    def _cancel_command_refreshes(self, vehicle_id: str | None = None) -> None:
        """Cancel delayed command refreshes for one or all vehicles."""
        if vehicle_id is not None:
            if cancel := self._command_refresh_cancels.pop(vehicle_id, None):
                cancel()
            return

        for cancel in self._command_refresh_cancels.values():
            cancel()
        self._command_refresh_cancels.clear()

    def _command_state_matches(self, vehicle_id: str, method: str) -> bool:
        """Return whether refreshed data matches a command's expected result."""
        expectation = COMMAND_EXPECTATIONS.get(method)
        if expectation is None:
            return True
        vehicle_data = self.data.get(vehicle_id)
        if vehicle_data is None:
            return False
        attribute, expected = expectation
        return getattr(vehicle_data.status, attribute) is expected

    def _schedule_command_refreshes(self, vehicle_id: str, method: str) -> None:
        """Retry refreshes until data matches the command's expected result."""
        self._cancel_command_refreshes(vehicle_id)
        intervals = iter(COMMAND_REFRESH_RETRY_INTERVALS)

        async def _async_refresh(_now: object) -> None:
            self._command_refresh_cancels.pop(vehicle_id, None)
            await self.async_request_refresh()
            if not self._command_state_matches(vehicle_id, method):
                _schedule_next()

        def _schedule_next() -> None:
            if interval := next(intervals, None):
                self._command_refresh_cancels[vehicle_id] = async_call_later(
                    self.hass,
                    interval,
                    _async_refresh,
                )

        _schedule_next()

    async def async_shutdown(self) -> None:
        """Cancel pending command refreshes and shut down the coordinator."""
        self._cancel_command_refreshes()
        if self._location_update_cancel is not None:
            self._location_update_cancel()
            self._location_update_cancel = None
        if self._location_refresh_cancel is not None:
            self._location_refresh_cancel()
            self._location_refresh_cancel = None
        await super().async_shutdown()

    def _fetch_vehicles(self) -> dict[str, DroneMobileVehicleData]:
        """Fetch vehicles and statuses from the blocking client."""
        vehicles = self.client.get_vehicles()
        return {
            vehicle.vehicle_id: DroneMobileVehicleData(
                vehicle=vehicle,
                status=vehicle.get_status(use_cache=True),
            )
            for vehicle in vehicles
        }

    async def _async_update_data(self) -> dict[str, DroneMobileVehicleData]:
        """Fetch the latest account data."""
        try:
            return await self.hass.async_add_executor_job(self._fetch_vehicles)
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except DroneMobileException as err:
            raise UpdateFailed(f"Unable to update DroneMobile data: {err}") from err

    async def async_execute_command(
        self, vehicle_id: str, method: str
    ) -> CommandResponse:
        """Execute an allow-listed vehicle method and refresh entity state."""
        vehicle_data = self.data.get(vehicle_id)
        if vehicle_data is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="vehicle_not_found",
            )

        if method not in COMMAND_METHODS:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_command",
            )
        command: Any
        if method == "get_location":
            command = partial(
                _request_location,
                self.client,
                vehicle_data.vehicle.device_key,
            )
        else:
            command = getattr(vehicle_data.vehicle, method)

        try:
            response = await self.hass.async_add_executor_job(command)
        except AuthenticationError as err:
            if self.config_entry:
                self.config_entry.async_start_reauth_if_available(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="authentication_failed",
            ) from err
        except DroneMobileException as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        if not response.success:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": response.message or "Unknown error"},
            )

        await self.async_request_refresh()
        if method == "get_location":
            self._last_location_request[vehicle_id] = dt_util.utcnow()
            self._schedule_location_refresh()
        elif method == "start":
            if await self._async_request_vehicle_location(
                vehicle_data,
                dt_util.utcnow(),
            ):
                self._schedule_location_refresh()
            if self._command_state_matches(vehicle_id, method):
                self._cancel_command_refreshes(vehicle_id)
            else:
                self._schedule_command_refreshes(vehicle_id, method)
        elif self._command_state_matches(vehicle_id, method):
            self._cancel_command_refreshes(vehicle_id)
        else:
            self._schedule_command_refreshes(vehicle_id, method)
        return response
