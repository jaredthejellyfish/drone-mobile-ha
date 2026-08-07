"""Button entities for DroneMobile vehicle commands."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DroneMobileCoordinator
from .entity import DroneMobileEntity, async_setup_vehicle_entities


@dataclass(frozen=True, kw_only=True)
class DroneMobileButtonDescription(ButtonEntityDescription):
    """Describe a DroneMobile command button."""

    method: str


BUTTONS: tuple[DroneMobileButtonDescription, ...] = (
    DroneMobileButtonDescription(
        key="trunk",
        translation_key="trunk",
        icon="mdi:car-back",
        method="trunk",
    ),
    DroneMobileButtonDescription(
        key="panic_on",
        translation_key="panic_on",
        icon="mdi:alarm-light",
        method="panic_on",
    ),
    DroneMobileButtonDescription(
        key="panic_off",
        translation_key="panic_off",
        icon="mdi:alarm-light-off",
        method="panic_off",
    ),
    DroneMobileButtonDescription(
        key="aux1",
        translation_key="aux1",
        icon="mdi:numeric-1-circle",
        method="aux1",
    ),
    DroneMobileButtonDescription(
        key="aux2",
        translation_key="aux2",
        icon="mdi:numeric-2-circle",
        method="aux2",
    ),
    DroneMobileButtonDescription(
        key="request_location",
        translation_key="request_location",
        icon="mdi:crosshairs-gps",
        method="get_location",
    ),
    DroneMobileButtonDescription(
        key="request_status",
        translation_key="request_status",
        icon="mdi:refresh",
        method="poll_status",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up DroneMobile command buttons."""
    coordinator: DroneMobileCoordinator = entry.runtime_data
    async_setup_vehicle_entities(
        entry,
        coordinator,
        async_add_entities,
        lambda vehicle_id: (
            DroneMobileCommandButton(coordinator, vehicle_id, description)
            for description in BUTTONS
        ),
    )


class DroneMobileCommandButton(DroneMobileEntity, ButtonEntity):
    """A button that sends a DroneMobile command."""

    entity_description: DroneMobileButtonDescription

    def __init__(
        self,
        coordinator: DroneMobileCoordinator,
        vehicle_id: str,
        description: DroneMobileButtonDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, vehicle_id, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Send the configured command."""
        await self.coordinator.async_execute_command(
            self.vehicle_id,
            self.entity_description.method,
        )
