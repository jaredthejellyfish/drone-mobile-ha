"""Base entities for the DroneMobile integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from drone_mobile import VehicleInfo

from .const import DOMAIN
from .coordinator import DroneMobileCoordinator, DroneMobileVehicleData


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
        self._attr_unique_id = f"{vehicle_id}_{key}"

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
            identifiers={(DOMAIN, self.vehicle_id)},
            name=info.name,
            manufacturer="Firstech",
            model=model,
            serial_number=info.vin,
            suggested_area="Garage",
        )
