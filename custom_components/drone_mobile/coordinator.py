"""Data coordinator for DroneMobile vehicles."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from drone_mobile import (
    AuthenticationError,
    CommandResponse,
    DroneMobileClient,
    DroneMobileException,
    Vehicle,
    VehicleStatus,
)

from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN

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
        command: Any = getattr(vehicle_data.vehicle, method)

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
        return response
