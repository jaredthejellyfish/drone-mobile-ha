"""Tests for DroneMobile sensor definitions."""

from homeassistant.const import UnitOfTemperature

from custom_components.drone_mobile.sensor import SENSORS


def test_interior_temperature_is_celsius() -> None:
    """The API reports interior temperature natively in Celsius."""
    description = next(
        sensor for sensor in SENSORS if sensor.key == "interior_temperature"
    )

    assert description.native_unit_of_measurement == UnitOfTemperature.CELSIUS
