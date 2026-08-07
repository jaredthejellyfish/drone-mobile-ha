"""Device tracker entities for DroneMobile vehicles."""

from __future__ import annotations

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DroneMobileCoordinator
from .entity import DroneMobileEntity, async_setup_vehicle_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up DroneMobile vehicle trackers."""
    coordinator: DroneMobileCoordinator = entry.runtime_data
    async_setup_vehicle_entities(
        entry,
        coordinator,
        async_add_entities,
        lambda vehicle_id: [DroneMobileVehicleTracker(coordinator, vehicle_id)],
    )


class DroneMobileVehicleTracker(DroneMobileEntity, TrackerEntity):
    """GPS location of a DroneMobile vehicle."""

    _attr_icon = "mdi:car-connected"
    _attr_translation_key = "location"

    def __init__(self, coordinator: DroneMobileCoordinator, vehicle_id: str) -> None:
        """Initialize the tracker."""
        super().__init__(coordinator, vehicle_id, "location")

    @property
    def source_type(self) -> SourceType:
        """Return the tracker source type."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Return latitude."""
        location = self.vehicle_data.status.location
        return location.latitude if location else None

    @property
    def longitude(self) -> float | None:
        """Return longitude."""
        location = self.vehicle_data.status.location
        return location.longitude if location else None

    @property
    def location_accuracy(self) -> int:
        """Return GPS accuracy in meters."""
        location = self.vehicle_data.status.location
        return int(location.accuracy or 0) if location else 0
