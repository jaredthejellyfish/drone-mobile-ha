"""Tests for DroneMobile vehicle entities."""

from __future__ import annotations

from unittest.mock import MagicMock

from drone_mobile import Vehicle, VehicleInfo, VehicleStatus

from custom_components.drone_mobile.binary_sensor import (
    DroneMobileRunningBinarySensor,
)
from custom_components.drone_mobile.coordinator import (
    COMMAND_EXPECTATIONS,
    DroneMobileCoordinator,
    DroneMobileVehicleData,
)
from custom_components.drone_mobile.device_tracker import DroneMobileVehicleTracker
from custom_components.drone_mobile.lock import DroneMobileDoorLock
from custom_components.drone_mobile.switch import DroneMobileEngineSwitch

VEHICLE_ID = "vehicle-123"


def make_coordinator() -> DroneMobileCoordinator:
    """Build a coordinator containing one representative vehicle."""
    info = VehicleInfo(
        vehicle_id=VEHICLE_ID,
        device_key="device-key",
        name="Daily Driver",
        make="Toyota",
        model="RAV4",
        year=2024,
        vin="TESTVIN",
    )
    vehicle = Vehicle(MagicMock(), info)
    status = VehicleStatus.from_dict(
        {
            "id": VEHICLE_ID,
            "device_key": "device-key",
            "last_known_state": {
                "latitude": 42.36,
                "longitude": -71.06,
                "controller": {"engine_on": True, "armed": True},
            },
        }
    )
    coordinator = MagicMock(spec=DroneMobileCoordinator)
    coordinator.data = {
        VEHICLE_ID: DroneMobileVehicleData(vehicle=vehicle, status=status)
    }
    coordinator.last_update_success = True
    return coordinator


def test_vehicle_state_entities() -> None:
    """Engine and lock state use the coordinator's latest snapshot."""
    coordinator = make_coordinator()

    assert DroneMobileEngineSwitch(coordinator, VEHICLE_ID).is_on is True
    assert DroneMobileRunningBinarySensor(coordinator, VEHICLE_ID).is_on is True
    assert DroneMobileDoorLock(coordinator, VEHICLE_ID).is_locked is True


def test_vehicle_tracker_and_device_info() -> None:
    """Location and vehicle metadata are exposed in Home Assistant form."""
    tracker = DroneMobileVehicleTracker(make_coordinator(), VEHICLE_ID)

    assert tracker.latitude == 42.36
    assert tracker.longitude == -71.06
    assert tracker.device_info["manufacturer"] == "Firstech"
    assert tracker.device_info["model"] == "Toyota RAV4"
    assert tracker.device_info["serial_number"] == "TESTVIN"


def test_command_expectations_match_refreshed_state() -> None:
    """Only retry commands whose observable result has not appeared yet."""
    coordinator = make_coordinator()

    matches = DroneMobileCoordinator._command_state_matches
    assert matches(coordinator, VEHICLE_ID, "start") is True
    assert matches(coordinator, VEHICLE_ID, "stop") is False
    assert matches(coordinator, VEHICLE_ID, "lock") is True
    assert matches(coordinator, VEHICLE_ID, "unlock") is False
    assert matches(coordinator, VEHICLE_ID, "trunk") is True
    assert set(COMMAND_EXPECTATIONS) == {"start", "stop", "lock", "unlock"}
