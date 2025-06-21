"""Sensor platform for the HDG Bavaria Boiler integration.

This module is responsible for creating and managing sensor entities that
represent various data points read from an HDG Bavaria boiler system.
It leverages the `HdgDataUpdateCoordinator` for data fetching and relies on
entity definitions specified in `definitions.py` to configure each sensor.
"""

from __future__ import annotations

__version__ = "0.8.28"

import logging
from typing import Any, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_SOURCE_TIMEZONE,
    DEFAULT_SOURCE_TIMEZONE,
    DOMAIN,
)
from .coordinator import HdgDataUpdateCoordinator
from .definitions import SENSOR_DEFINITIONS
from .entity import HdgNodeEntity
from .helpers.sensor_parsing_utils import parse_sensor_value
from .helpers.string_utils import strip_hdg_node_suffix
from .models import SensorDefinition

_LOGGER = logging.getLogger(DOMAIN)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HDG Bavaria sensor entities based on a configuration entry.

    Iterates through SENSOR_DEFINITIONS, creating sensor entities for those
    defined with `ha_platform: "sensor"`.

    Args:
        hass: The HomeAssistant instance.
        entry: The ConfigEntry instance for this integration.
        async_add_entities: Callback function to add entities to Home Assistant.

    """
    coordinator: HdgDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    entities: list[HdgBoilerSensor] = []

    for unique_id_suffix, entity_definition_dict in SENSOR_DEFINITIONS.items():
        entity_def = cast(SensorDefinition, entity_definition_dict)

        if entity_def.get("ha_platform") == "sensor":
            # Create a SensorEntityDescription from the custom SensorDefinition.
            # 'name' is set to None as HA will use the translation_key for naming.
            description = SensorEntityDescription(
                key=unique_id_suffix,
                name=None,
                icon=entity_def.get("icon"),
                device_class=cast(
                    SensorDeviceClass | None, entity_def.get("ha_device_class")
                ),
                native_unit_of_measurement=entity_def.get(
                    "ha_native_unit_of_measurement"
                ),
                state_class=entity_def.get("ha_state_class"),
                entity_category=entity_def.get("entity_category"),
                translation_key=entity_def.get("translation_key"),
            )
            entities.append(HdgBoilerSensor(coordinator, description, entity_def))
            _LOGGER.debug(
                f"Preparing HDG sensor for translation_key: {unique_id_suffix} "
                f"(HDG Node ID: {entity_def.get('hdg_node_id', 'N/A')})"
            )

    if entities:
        async_add_entities(entities)
        _LOGGER.info(f"Added {len(entities)} HDG Bavaria sensor entities.")
    else:
        _LOGGER.info("No sensor entities to add from SENSOR_DEFINITIONS.")


class HdgBoilerSensor(HdgNodeEntity, SensorEntity):
    """Represents an HDG Bavaria Boiler sensor entity.

    This class derives from `HdgNodeEntity` and `SensorEntity`. It is responsible
    for taking the raw data provided by the `HdgDataUpdateCoordinator` and parsing
    it into a displayable sensor state, according to its specific entity definition.
    """

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        entity_description: SensorEntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """Initialize the HDG Boiler sensor entity.

        Args:
            coordinator: The HdgDataUpdateCoordinator for managing entity data.
            entity_description: Standard Home Assistant SensorEntityDescription.
            entity_definition: Custom entity definition from SENSOR_DEFINITIONS.

        """
        # The hdg_node_id from the definition might include a suffix (T, U, etc.)
        # which needs to be stripped for data lookup in the coordinator.
        hdg_api_node_id_from_def = entity_definition["hdg_node_id"]
        super().__init__(
            coordinator,
            strip_hdg_node_suffix(hdg_api_node_id_from_def),
            cast(dict[str, Any], entity_definition),
        )
        self.entity_description = entity_description

        # Initialize native_value and update state based on current coordinator data.
        self._attr_native_value = None
        self._update_sensor_state()

        _LOGGER.debug(f"HdgBoilerSensor {self.entity_description.key}: Initialized.")

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the HdgDataUpdateCoordinator."""
        self._update_sensor_state()
        super()._handle_coordinator_update()

    def _update_sensor_state(self) -> None:
        """Update the sensor's internal state from the coordinator's data."""
        # First, update availability based on the base class logic.
        self._attr_available = super().available

        if not self._attr_available:
            self._attr_native_value = None
            return

        # Retrieve the raw value for this sensor's node ID from the coordinator.
        raw_value_text = self.coordinator.data.get(self._node_id)
        # Parse the raw value using the centralized parsing utility.
        self._attr_native_value = parse_sensor_value(
            raw_value_text=raw_value_text,
            entity_definition=self._entity_definition,  # Pass the full definition
            node_id_for_log=self._node_id,
            entity_id_for_log=self.entity_id,
            configured_timezone=self.coordinator.entry.options.get(
                CONF_SOURCE_TIMEZONE, DEFAULT_SOURCE_TIMEZONE
            ),
        )
