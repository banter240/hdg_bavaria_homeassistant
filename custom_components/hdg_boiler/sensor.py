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
    ENTITY_DETAIL_LOGGER_NAME,
    LIFECYCLE_LOGGER_NAME,
)
from .coordinator import HdgDataUpdateCoordinator
from .definitions import SENSOR_DEFINITIONS
from .entity import HdgNodeEntity
from .helpers.entity_utils import create_entity_description
from .helpers.parsers import parse_sensor_value
from .helpers.string_utils import strip_hdg_node_suffix
from .models import SensorDefinition

_LOGGER = logging.getLogger(DOMAIN)
_ENTITY_DETAIL_LOGGER = logging.getLogger(ENTITY_DETAIL_LOGGER_NAME)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)


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

    for translation_key, entity_def in SENSOR_DEFINITIONS.items():
        if entity_def.get("ha_platform") == "sensor":
            description = create_entity_description(
                SensorEntityDescription, translation_key, entity_def
            )
            entities.append(HdgBoilerSensor(coordinator, description, entity_def))
            _ENTITY_DETAIL_LOGGER.debug(
                "Preparing HDG sensor for translation_key: %s (HDG Node ID: %s)",
                translation_key,
                entity_def.get("hdg_node_id", "N/A"),
            )

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %s HDG Bavaria sensor entities.", len(entities))
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
        self.entity_description = entity_description
        # The hdg_node_id from the definition might include a suffix (T, U, etc.)
        # which needs to be stripped for data lookup in the coordinator.
        hdg_api_node_id_from_def = entity_definition["hdg_node_id"]
        super().__init__(
            coordinator,
            strip_hdg_node_suffix(hdg_api_node_id_from_def),
            cast(dict[str, Any], entity_definition),
        )

        # Initialize native_value and update state based on current coordinator data.
        self._attr_native_value = None
        self._update_sensor_state()

        _LIFECYCLE_LOGGER.debug(
            "HdgBoilerSensor %s: Initialized.", self.entity_description.key
        )

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
        parsed_value = parse_sensor_value(
            raw_value_text=raw_value_text,
            entity_definition=self._entity_definition,  # Pass the full definition
            node_id_for_log=self._node_id,
            entity_id_for_log=self.entity_id,
            configured_timezone=self.coordinator.entry.options.get(
                CONF_SOURCE_TIMEZONE, DEFAULT_SOURCE_TIMEZONE
            ),
        )
        self._attr_native_value = parsed_value
        _ENTITY_DETAIL_LOGGER.debug(
            "Entity %s (Node ID: %s): Updated state. Raw: '%s', Parsed: '%s'",
            self.entity_id,
            self._node_id,
            raw_value_text,
            parsed_value,
        )
