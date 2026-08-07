"""Tests for DroneMobile vehicle entities."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from drone_mobile import CommandResponse, Vehicle, VehicleInfo, VehicleStatus
from homeassistant.const import CONF_USERNAME

from custom_components.drone_mobile.api import account_id
from custom_components.drone_mobile.binary_sensor import (
    DroneMobileRunningBinarySensor,
)
from custom_components.drone_mobile.const import (
    DOMAIN,
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
USERNAME = "user@example.com"


def make_coordinator(username: str = USERNAME) -> DroneMobileCoordinator:
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
    coordinator.config_entry = MagicMock()
    coordinator.config_entry.data = {CONF_USERNAME: username}
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
    scoped_id = account_id(USERNAME)

    assert tracker.latitude == 42.36
    assert tracker.longitude == -71.06
    assert tracker.unique_id == f"{scoped_id}_{VEHICLE_ID}_location"
    assert tracker.device_info["identifiers"] == {(DOMAIN, f"{scoped_id}_{VEHICLE_ID}")}
    assert tracker.device_info["manufacturer"] == "Firstech"
    assert tracker.device_info["model"] == "Toyota RAV4"
    assert tracker.device_info["serial_number"] == "TESTVIN"
    assert USERNAME not in tracker.unique_id
    assert USERNAME not in str(tracker.device_info["identifiers"])


def test_shared_vehicle_ids_are_scoped_per_account() -> None:
    """Two accounts sharing a vehicle ID keep distinct entity and device IDs."""
    first = DroneMobileVehicleTracker(make_coordinator("alice@example.com"), VEHICLE_ID)
    second = DroneMobileVehicleTracker(make_coordinator("bob@example.com"), VEHICLE_ID)

    assert first.unique_id != second.unique_id
    assert first.device_info["identifiers"] != second.device_info["identifiers"]
    assert first.unique_id == f"{account_id('alice@example.com')}_{VEHICLE_ID}_location"
    assert second.unique_id == f"{account_id('bob@example.com')}_{VEHICLE_ID}_location"
    assert first.device_info["identifiers"] == {
        (DOMAIN, f"{account_id('alice@example.com')}_{VEHICLE_ID}")
    }
    assert second.device_info["identifiers"] == {
        (DOMAIN, f"{account_id('bob@example.com')}_{VEHICLE_ID}")
    }


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
        _client_lock=asyncio.Lock(),
        _client_closed=False,
        _last_location_request={},
    )
    coordinator._async_call_client = MethodType(
        DroneMobileCoordinator._async_call_client,
        coordinator,
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


def test_client_calls_are_serialized() -> None:
    """Refresh, location, and command work never overlap on the shared client."""

    async def _run() -> None:
        active = 0
        max_active = 0
        started = asyncio.Event()
        release = asyncio.Event()
        entered = 0
        vehicle_data = make_coordinator().data[VEHICLE_ID]
        vehicles = {VEHICLE_ID: vehicle_data}
        lock_response = CommandResponse(
            success=True,
            message="ok",
            command="lock",
            device_key="device-key",
        )
        location_response = CommandResponse(
            success=True,
            message="ok",
            command=LOCATION_COMMAND,
            device_key="device-key",
        )

        def fetch_vehicles() -> dict[str, DroneMobileVehicleData]:
            return vehicles

        def lock_command() -> CommandResponse:
            return lock_response

        vehicle_data.vehicle.lock = lock_command

        async def fake_executor(func, *args):
            nonlocal active, max_active, entered
            entered += 1
            active += 1
            max_active = max(max_active, active)
            if entered == 1:
                started.set()
            await release.wait()
            active -= 1
            if func is fetch_vehicles:
                return vehicles
            if func is _request_location:
                return location_response
            if func is lock_command:
                return lock_response
            raise AssertionError(f"unexpected client call: {func!r}")

        hass = MagicMock()
        hass.async_add_executor_job = fake_executor
        coordinator = SimpleNamespace(
            hass=hass,
            client=MagicMock(),
            config_entry=None,
            data=vehicles,
            _client_lock=asyncio.Lock(),
            _client_closed=False,
            _last_location_request={},
            _fetch_vehicles=fetch_vehicles,
            async_request_refresh=AsyncMock(),
            _command_state_matches=lambda *_args: True,
            _cancel_command_refreshes=MagicMock(),
            _schedule_command_refreshes=MagicMock(),
        )
        coordinator._async_call_client = MethodType(
            DroneMobileCoordinator._async_call_client,
            coordinator,
        )

        refresh = asyncio.create_task(
            DroneMobileCoordinator._async_update_data(coordinator)
        )
        await started.wait()
        location = asyncio.create_task(
            DroneMobileCoordinator._async_request_vehicle_location(
                coordinator,
                vehicle_data,
                datetime.now(UTC),
            )
        )
        command = asyncio.create_task(
            DroneMobileCoordinator.async_execute_command(
                coordinator,
                VEHICLE_ID,
                "lock",
            )
        )
        # Give the queued callers a chance to contend for the lock.
        await asyncio.sleep(0)
        assert entered == 1
        assert max_active == 1
        release.set()
        await asyncio.gather(refresh, location, command)
        assert entered == 3
        assert max_active == 1

    asyncio.run(_run())


def test_shutdown_waits_for_in_flight_client_work() -> None:
    """Unload closes the client only after in-flight executor work finishes."""

    async def _run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        closed_before_release = False
        vehicles = {VEHICLE_ID: make_coordinator().data[VEHICLE_ID]}

        def fetch_vehicles() -> dict[str, DroneMobileVehicleData]:
            return vehicles

        client = MagicMock()

        async def fake_executor(func, *args):
            nonlocal closed_before_release
            if func is client.close:
                closed_before_release = not release.is_set()
                return None
            assert func is fetch_vehicles
            started.set()
            await release.wait()
            return vehicles

        hass = MagicMock()
        hass.async_add_executor_job = fake_executor
        coordinator = SimpleNamespace(
            hass=hass,
            client=client,
            _client_lock=asyncio.Lock(),
            _client_closed=False,
            _command_refresh_cancels={},
            _location_update_cancel=None,
            _location_refresh_cancel=None,
            _fetch_vehicles=fetch_vehicles,
            _cancel_command_refreshes=MagicMock(),
        )
        coordinator._async_call_client = MethodType(
            DroneMobileCoordinator._async_call_client,
            coordinator,
        )

        refresh = asyncio.create_task(
            DroneMobileCoordinator._async_update_data(coordinator)
        )
        await started.wait()
        shutdown = asyncio.create_task(_async_shutdown_without_super(coordinator))
        await asyncio.sleep(0)
        assert coordinator._client_closed is False
        release.set()
        await refresh
        await shutdown
        assert coordinator._client_closed is True
        assert closed_before_release is False

    async def _async_shutdown_without_super(coordinator: SimpleNamespace) -> None:
        """Mirror async_shutdown's client drain/close without the HA base class."""
        coordinator._cancel_command_refreshes()
        if coordinator._location_update_cancel is not None:
            coordinator._location_update_cancel()
            coordinator._location_update_cancel = None
        if coordinator._location_refresh_cancel is not None:
            coordinator._location_refresh_cancel()
            coordinator._location_refresh_cancel = None
        async with coordinator._client_lock:
            if not coordinator._client_closed:
                await coordinator.hass.async_add_executor_job(coordinator.client.close)
                coordinator._client_closed = True

    asyncio.run(_run())
