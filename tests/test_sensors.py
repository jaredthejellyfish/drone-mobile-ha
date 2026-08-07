"""Tests for DroneMobile sensor definitions and dynamic entity setup."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from drone_mobile import Location, Vehicle, VehicleInfo, VehicleStatus
from homeassistant.const import CONF_USERNAME, UnitOfTemperature

from custom_components.drone_mobile import device_tracker, lock, sensor
from custom_components.drone_mobile.api import account_id
from custom_components.drone_mobile.coordinator import DroneMobileVehicleData
from custom_components.drone_mobile.device_tracker import DroneMobileVehicleTracker
from custom_components.drone_mobile.entity import async_setup_vehicle_entities
from custom_components.drone_mobile.lock import DroneMobileDoorLock
from custom_components.drone_mobile.sensor import SENSORS, DroneMobileSensor

VEHICLE_ID = "vehicle-123"
NEW_VEHICLE_ID = "vehicle-456"
USERNAME = "user@example.com"
ACCOUNT_ID = account_id(USERNAME)


def _vehicle_data(
    vehicle_id: str,
    *,
    location: Location | None = None,
) -> DroneMobileVehicleData:
    """Build coordinator vehicle data for tests."""
    info = VehicleInfo(
        vehicle_id=vehicle_id,
        device_key=f"device-{vehicle_id}",
        name=f"Vehicle {vehicle_id}",
        make="Toyota",
        model="RAV4",
        year=2024,
        vin=f"VIN{vehicle_id}",
    )
    status = VehicleStatus(
        vehicle_id=vehicle_id,
        device_key=info.device_key,
        location=location,
    )
    return DroneMobileVehicleData(vehicle=Vehicle(MagicMock(), info), status=status)


def _mock_entry(coordinator: MagicMock) -> MagicMock:
    """Build a config entry that records unload callbacks."""
    entry = MagicMock()
    entry.runtime_data = coordinator
    unload_callbacks: list = []
    entry.async_on_unload.side_effect = unload_callbacks.append
    return entry


def _mock_coordinator(data: dict[str, DroneMobileVehicleData]) -> MagicMock:
    """Build a coordinator that can notify discovery listeners."""
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.config_entry = MagicMock()
    coordinator.config_entry.data = {CONF_USERNAME: USERNAME}
    listeners: list = []
    coordinator._listeners = listeners

    def async_add_listener(callback):
        listeners.append(callback)
        return lambda: listeners.remove(callback)

    coordinator.async_add_listener.side_effect = async_add_listener
    return coordinator


def test_interior_temperature_is_celsius() -> None:
    """The API reports interior temperature natively in Celsius."""
    description = next(
        sensor_desc
        for sensor_desc in SENSORS
        if sensor_desc.key == "interior_temperature"
    )

    assert description.native_unit_of_measurement == UnitOfTemperature.CELSIUS


def test_sensors_omit_unsupported_library_values() -> None:
    """Battery percent and fuel level stay reserved until the library provides them."""
    assert {sensor_desc.key for sensor_desc in SENSORS} == {
        "battery_voltage",
        "odometer",
        "interior_temperature",
        "last_updated",
    }


def test_tracker_created_without_location_updates_when_available() -> None:
    """Trackers exist before the first fix and report coordinates once present."""
    coordinator = MagicMock()
    coordinator.data = {VEHICLE_ID: _vehicle_data(VEHICLE_ID)}
    coordinator.last_update_success = True
    coordinator.config_entry = MagicMock()
    coordinator.config_entry.data = {CONF_USERNAME: USERNAME}
    tracker = DroneMobileVehicleTracker(coordinator, VEHICLE_ID)

    assert tracker.latitude is None
    assert tracker.longitude is None

    updated = _vehicle_data(
        VEHICLE_ID,
        location=Location(latitude=42.36, longitude=-71.06),
    )
    coordinator.data = {VEHICLE_ID: updated}

    assert tracker.latitude == 42.36
    assert tracker.longitude == -71.06


def test_sensors_created_when_values_are_initially_unknown() -> None:
    """Sensors are created even when the first snapshot has no values."""
    coordinator = _mock_coordinator({VEHICLE_ID: _vehicle_data(VEHICLE_ID)})
    entry = _mock_entry(coordinator)
    added: list = []

    asyncio.run(sensor.async_setup_entry(MagicMock(), entry, added.extend))

    assert len(added) == len(SENSORS)
    assert all(isinstance(entity, DroneMobileSensor) for entity in added)
    assert all(entity.native_value is None for entity in added)


def test_new_vehicle_adds_entities_after_setup() -> None:
    """Platforms register entities for vehicles that appear after startup."""
    coordinator = _mock_coordinator({VEHICLE_ID: _vehicle_data(VEHICLE_ID)})
    entry = _mock_entry(coordinator)
    added: list = []

    asyncio.run(lock.async_setup_entry(MagicMock(), entry, added.extend))
    asyncio.run(device_tracker.async_setup_entry(MagicMock(), entry, added.extend))

    assert {entity.unique_id for entity in added} == {
        f"{ACCOUNT_ID}_{VEHICLE_ID}_doors",
        f"{ACCOUNT_ID}_{VEHICLE_ID}_location",
    }
    assert len(coordinator._listeners) == 2

    coordinator.data = {
        VEHICLE_ID: _vehicle_data(VEHICLE_ID),
        NEW_VEHICLE_ID: _vehicle_data(NEW_VEHICLE_ID),
    }
    for listener in list(coordinator._listeners):
        listener()

    assert {entity.unique_id for entity in added} == {
        f"{ACCOUNT_ID}_{VEHICLE_ID}_doors",
        f"{ACCOUNT_ID}_{VEHICLE_ID}_location",
        f"{ACCOUNT_ID}_{NEW_VEHICLE_ID}_doors",
        f"{ACCOUNT_ID}_{NEW_VEHICLE_ID}_location",
    }


def test_discovery_listener_is_idempotent() -> None:
    """Repeated coordinator updates do not re-add entities for known vehicles."""
    coordinator = _mock_coordinator({VEHICLE_ID: _vehicle_data(VEHICLE_ID)})
    entry = SimpleNamespace(async_on_unload=MagicMock())
    entry.async_on_unload.side_effect = lambda func: None
    added: list = []

    async_setup_vehicle_entities(
        entry,
        coordinator,
        added.extend,
        lambda vehicle_id: [DroneMobileDoorLock(coordinator, vehicle_id)],
    )
    assert len(added) == 1

    for listener in coordinator._listeners:
        listener()
        listener()

    assert len(added) == 1
    assert isinstance(added[0], DroneMobileDoorLock)
