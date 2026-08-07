"""Sensor entities for DroneMobile vehicles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from drone_mobile import VehicleStatus

from .coordinator import DroneMobileCoordinator
from .entity import DroneMobileEntity, async_setup_vehicle_entities


@dataclass(frozen=True, kw_only=True)
class DroneMobileSensorDescription(SensorEntityDescription):
    """Describe a DroneMobile sensor."""

    value_fn: Callable[[VehicleStatus], Any]


# battery_percent and fuel_level are reserved until the library can populate them.
SENSORS: tuple[DroneMobileSensorDescription, ...] = (
    DroneMobileSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda status: status.battery_voltage,
    ),
    DroneMobileSensorDescription(
        key="odometer",
        translation_key="odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.MILES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda status: status.odometer,
    ),
    DroneMobileSensorDescription(
        key="interior_temperature",
        translation_key="interior_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda status: status.interior_temperature,
    ),
    DroneMobileSensorDescription(
        key="last_updated",
        translation_key="last_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda status: status.last_updated,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up DroneMobile sensors."""
    coordinator: DroneMobileCoordinator = entry.runtime_data
    async_setup_vehicle_entities(
        entry,
        coordinator,
        async_add_entities,
        lambda vehicle_id: (
            DroneMobileSensor(coordinator, vehicle_id, description)
            for description in SENSORS
        ),
    )


class DroneMobileSensor(DroneMobileEntity, SensorEntity):
    """A sensor sourced from DroneMobile vehicle status."""

    entity_description: DroneMobileSensorDescription

    def __init__(
        self,
        coordinator: DroneMobileCoordinator,
        vehicle_id: str,
        description: DroneMobileSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, vehicle_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | datetime | None:
        """Return the latest sensor value."""
        return self.entity_description.value_fn(self.vehicle_data.status)
