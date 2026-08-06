"""Binary sensor entities for DroneMobile vehicles."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DroneMobileCoordinator
from .entity import DroneMobileEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up DroneMobile binary sensors."""
    coordinator: DroneMobileCoordinator = entry.runtime_data
    async_add_entities(
        DroneMobileRunningBinarySensor(coordinator, vehicle_id)
        for vehicle_id in coordinator.data
    )


class DroneMobileRunningBinarySensor(DroneMobileEntity, BinarySensorEntity):
    """Vehicle running status."""

    _attr_icon = "mdi:engine"
    _attr_translation_key = "running"

    def __init__(self, coordinator: DroneMobileCoordinator, vehicle_id: str) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, vehicle_id, "running")

    @property
    def is_on(self) -> bool:
        """Return whether the engine is running."""
        return self.vehicle_data.status.is_running
