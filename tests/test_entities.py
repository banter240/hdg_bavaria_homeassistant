"""Tests for entity construction and value behaviour (harness venv).

Instantiates real entities against a stub coordinator and the real
registry/definitions. Run with:

    dev/tmp/phacc/venv/bin/python -m pytest tests/test_entities.py -q
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, cast

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory

from custom_components.hdg_boiler.const import (
    CONF_DEVICE_ALIAS,
    CONF_ENABLE_FEUERUNG,
    CONF_ENABLE_WAERMEPUMPE,
    CONF_HOST_IP,
    DOMAIN,
)
from custom_components.hdg_boiler.definitions import get_sensor_definitions
from custom_components.hdg_boiler.helpers.entity_utils import (
    create_entity_description,
)
from custom_components.hdg_boiler.registry import HdgEntityRegistry
from custom_components.hdg_boiler.sensor import HdgBoilerSensor

OPTIONS = {
    CONF_ENABLE_FEUERUNG: True,
    CONF_ENABLE_WAERMEPUMPE: True,
}


def _registry(options: dict[str, Any] | None = None) -> HdgEntityRegistry:
    return HdgEntityRegistry(
        get_sensor_definitions(options if options is not None else OPTIONS),
        [],
    )


def _stub_coordinator(
    data: dict[str, Any] | None = None,
    *,
    last_update_success: bool = True,
) -> Any:
    entry = SimpleNamespace(
        data={CONF_HOST_IP: "192.0.2.1", CONF_DEVICE_ALIAS: "Testofen"},
        unique_id="192.0.2.1",
        entry_id="test-entry",
        options=OPTIONS,
    )
    return cast(
        Any,
        SimpleNamespace(
            entry=entry,
            data=data if data is not None else {},
            last_update_success=last_update_success,
            api_client=SimpleNamespace(base_url="http://192.0.2.1"),
        ),
    )


def _sensor(key: str, coordinator: Any = None) -> HdgBoilerSensor:
    registry = _registry()
    definition = registry.get_entities_for_platform("sensor")[key]
    description = create_entity_description("sensor", key, definition)
    coord = coordinator if coordinator is not None else _stub_coordinator()
    return HdgBoilerSensor(coord, description, definition)


class TestConstruction(unittest.TestCase):
    def test_unique_id_format(self) -> None:
        entity = _sensor("kesseltemperatur_ist")
        self.assertEqual(
            entity.unique_id, "hdg_boiler::Testofen::kesseltemperatur_ist_sensor"
        )

    def test_device_info_from_alias(self) -> None:
        entity = _sensor("kesseltemperatur_ist")
        info = entity.device_info
        assert info is not None
        self.assertEqual(info["identifiers"], {(DOMAIN, "Testofen")})
        self.assertEqual(info["name"], "HDG Boiler (Testofen)")

    def test_temp_sensor_classes_and_units(self) -> None:
        entity = _sensor("kesseltemperatur_ist")
        self.assertEqual(entity.device_class, SensorDeviceClass.TEMPERATURE)
        self.assertEqual(entity.state_class, SensorStateClass.MEASUREMENT)
        self.assertEqual(entity.native_unit_of_measurement, "°C")

    def test_diagnostic_category_propagates(self) -> None:
        entity = _sensor("mac_adresse")
        self.assertEqual(entity.entity_category, EntityCategory.DIAGNOSTIC)

    def test_component_group_toggle_disables_entities(self) -> None:
        # heat pump group switched off: its lifetime stats start disabled
        registry = _registry({CONF_ENABLE_WAERMEPUMPE: False})
        key = "wp_stat_schaltzyklen_reset"
        definition = registry.get_entities_for_platform("sensor")[key]
        description = create_entity_description("sensor", key, definition)
        wp_entity = HdgBoilerSensor(_stub_coordinator(), description, definition)
        self.assertFalse(wp_entity._attr_entity_registry_enabled_default)


class TestAvailabilityAndValue(unittest.TestCase):
    def test_unavailable_without_data(self) -> None:
        entity = _sensor("kesseltemperatur_ist")
        self.assertFalse(entity.available)
        self.assertIsNone(entity.native_value)

    def test_value_passthrough_when_available(self) -> None:
        entity = _sensor(
            "kesseltemperatur_ist", _stub_coordinator(data={"22003": 65.5})
        )
        self.assertTrue(entity.available)
        self.assertEqual(entity.native_value, 65.5)

    def test_unavailable_marker_string(self) -> None:
        entity = _sensor(
            "kesseltemperatur_ist", _stub_coordinator(data={"22003": "---"})
        )
        self.assertFalse(entity.available)

    def test_failed_last_update_unavailable(self) -> None:
        coord = _stub_coordinator(data={"22003": 65.5}, last_update_success=False)
        entity = _sensor("kesseltemperatur_ist", coord)
        self.assertFalse(entity.available)

    def test_attributes_expose_node_metadata(self) -> None:
        entity = _sensor(
            "kesseltemperatur_ist", _stub_coordinator(data={"22003": 65.5})
        )
        attrs = entity.extra_state_attributes
        self.assertEqual(attrs["hdg_node_id"], "22003")


if __name__ == "__main__":
    unittest.main()
