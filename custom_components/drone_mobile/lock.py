"""Lock entities for DroneMobile vehicles."""

from __future__ import annotations

from homeassistant.components.lock import LockEntity
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
    """Set up DroneMobile lock entities."""
    coordinator: DroneMobileCoordinator = entry.runtime_data
    async_add_entities(
        DroneMobileDoorLock(coordinator, vehicle_id) for vehicle_id in coordinator.data
    )


class DroneMobileDoorLock(DroneMobileEntity, LockEntity):
    """A vehicle door lock."""

    _attr_translation_key = "doors"

    def __init__(self, coordinator: DroneMobileCoordinator, vehicle_id: str) -> None:
        """Initialize the lock."""
        super().__init__(coordinator, vehicle_id, "doors")

    @property
    def is_locked(self) -> bool:
        """Return whether the vehicle is locked."""
        return self.vehicle_data.status.is_locked

    async def async_lock(self, **kwargs: object) -> None:
        """Lock the vehicle."""
        await self.coordinator.async_execute_command(self.vehicle_id, "lock")

    async def async_unlock(self, **kwargs: object) -> None:
        """Unlock the vehicle."""
        await self.coordinator.async_execute_command(self.vehicle_id, "unlock")
