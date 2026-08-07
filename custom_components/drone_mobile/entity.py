"""Base entities for the DroneMobile integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from drone_mobile import VehicleInfo

from .api import account_id
from .const import DOMAIN
from .coordinator import DroneMobileCoordinator, DroneMobileVehicleData


def async_setup_vehicle_entities(
    entry: ConfigEntry,
    coordinator: DroneMobileCoordinator,
    async_add_entities: AddEntitiesCallback,
    create_entities: Callable[[str], Iterable[Entity]],
) -> None:
    """Add entities for known vehicles and any vehicles discovered later."""
    known_vehicle_ids: set[str] = set()

    @callback
    def _async_discover() -> None:
        new_ids = set(coordinator.data) - known_vehicle_ids
        if not new_ids:
            return
        known_vehicle_ids.update(new_ids)
        async_add_entities(
            entity for vehicle_id in new_ids for entity in create_entities(vehicle_id)
        )

    _async_discover()
    entry.async_on_unload(coordinator.async_add_listener(_async_discover))


class DroneMobileEntity(CoordinatorEntity[DroneMobileCoordinator]):
    """Base class for an entity belonging to a DroneMobile vehicle."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DroneMobileCoordinator,
        vehicle_id: str,
        key: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.vehicle_id = vehicle_id
        # Scope IDs to the account so shared vehicles across config entries do
        # not collide in the entity or device registries.
        self._account_id = account_id(coordinator.config_entry.data[CONF_USERNAME])
        self._attr_unique_id = f"{self._account_id}_{vehicle_id}_{key}"

    @property
    def vehicle_data(self) -> DroneMobileVehicleData:
        """Return the latest vehicle data."""
        return self.coordinator.data[self.vehicle_id]

    @property
    def available(self) -> bool:
        """Return whether the vehicle is available."""
        return super().available and self.vehicle_id in self.coordinator.data

    @property
    def device_info(self) -> DeviceInfo:
        """Return vehicle information for the device registry."""
        info: VehicleInfo = self.vehicle_data.vehicle.info
        model = " ".join(part for part in (info.make, info.model) if part) or None
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._account_id}_{self.vehicle_id}")},
            name=info.name,
            manufacturer="Firstech",
            model=model,
            serial_number=info.vin,
            suggested_area="Garage",
        )
