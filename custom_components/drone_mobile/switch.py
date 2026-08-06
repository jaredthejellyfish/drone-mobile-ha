"""Switch entities for DroneMobile vehicles."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
    """Set up DroneMobile switch entities."""
    coordinator: DroneMobileCoordinator = entry.runtime_data
    async_add_entities(
        DroneMobileEngineSwitch(coordinator, vehicle_id)
        for vehicle_id in coordinator.data
    )


class DroneMobileEngineSwitch(DroneMobileEntity, SwitchEntity):
    """A remote-start engine switch."""

    _attr_icon = "mdi:engine"
    _attr_translation_key = "engine"

    def __init__(self, coordinator: DroneMobileCoordinator, vehicle_id: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, vehicle_id, "engine")

    @property
    def is_on(self) -> bool:
        """Return whether the engine is running."""
        return self.vehicle_data.status.is_running

    async def async_turn_on(self, **kwargs: object) -> None:
        """Start the engine."""
        await self.coordinator.async_execute_command(self.vehicle_id, "start")

    async def async_turn_off(self, **kwargs: object) -> None:
        """Stop the engine."""
        await self.coordinator.async_execute_command(self.vehicle_id, "stop")
