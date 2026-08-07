"""Tests for DroneMobile vehicle entities."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from drone_mobile import CommandResponse, Vehicle, VehicleInfo, VehicleStatus

from custom_components.drone_mobile.binary_sensor import (
    DroneMobileRunningBinarySensor,
)
from custom_components.drone_mobile.const import (
    LOCATION_UPDATE_INTERVAL,
    PARKED_LOCATION_UPDATE_INTERVAL,
)
from custom_components.drone_mobile.coordinator import (
    COMMAND_EXPECTATIONS,
    LOCATION_COMMAND,
    DroneMobileCoordinator,
    DroneMobileVehicleData,
    _request_location,
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


def test_location_uses_controller_command() -> None:
    """Location requests use the API's controller command syntax."""
    client = MagicMock()
    expected = MagicMock()
    client.send_command.return_value = expected

    assert _request_location(client, "device-key") is expected
    client.send_command.assert_called_once_with("device-key", LOCATION_COMMAND, "2")


def test_adaptive_location_update_schedule() -> None:
    """Running vehicles update every cycle while parked vehicles back off."""
    now = datetime.now(UTC)
    coordinator = SimpleNamespace(_last_location_request={})
    is_due = DroneMobileCoordinator._location_update_due

    assert is_due(coordinator, VEHICLE_ID, False, now) is True
    coordinator._last_location_request[VEHICLE_ID] = now
    assert is_due(coordinator, VEHICLE_ID, False, now) is False
    assert is_due(coordinator, VEHICLE_ID, True, now) is True

    later = now + PARKED_LOCATION_UPDATE_INTERVAL
    assert is_due(coordinator, VEHICLE_ID, False, later) is True
    assert LOCATION_UPDATE_INTERVAL == timedelta(minutes=5)
    assert PARKED_LOCATION_UPDATE_INTERVAL == timedelta(minutes=30)


def test_successful_location_request_records_time() -> None:
    """Successful requests record when the vehicle was last actively located."""
    now = datetime.now(UTC)
    vehicle_data = make_coordinator().data[VEHICLE_ID]
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(
        return_value=CommandResponse(
            success=True,
            message="Location requested",
            command=LOCATION_COMMAND,
            device_key="device-key",
        )
    )
    coordinator = SimpleNamespace(
        hass=hass,
        client=MagicMock(),
        config_entry=None,
        _last_location_request={},
    )

    success = asyncio.run(
        DroneMobileCoordinator._async_request_vehicle_location(
            coordinator,
            vehicle_data,
            now,
        )
    )

    assert success is True
    hass.async_add_executor_job.assert_awaited_once()
    assert coordinator._last_location_request[VEHICLE_ID] == now
