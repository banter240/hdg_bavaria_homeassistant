"""Sensor platform for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.2.0"
__all__ = ["async_setup_entry"]

import logging
from typing import Any, cast

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
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
from .entity import HdgNodeEntity
from .helpers.entity_utils import create_entity_description
from .helpers.parsers import parse_sensor_value
from .models import SensorDefinition
from .registry import HdgEntityRegistry

_LOGGER = logging.getLogger(DOMAIN)
_ENTITY_DETAIL_LOGGER = logging.getLogger(ENTITY_DETAIL_LOGGER_NAME)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HDG Bavaria sensor entities from a config entry."""
    integration_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HdgDataUpdateCoordinator = integration_data["coordinator"]
    hdg_entity_registry: HdgEntityRegistry = integration_data["hdg_entity_registry"]

    sensor_definitions = hdg_entity_registry.get_entities_for_platform("sensor")
    if entities := [
        HdgBoilerSensor(
            coordinator,
            create_entity_description("sensor", translation_key, entity_def),
            entity_def,
        )
        for translation_key, entity_def in sensor_definitions.items()
    ]:
        async_add_entities(entities)
        hdg_entity_registry.increment_added_entity_count("sensor", len(entities))
        _LIFECYCLE_LOGGER.info("Added %d HDG Bavaria sensor entities.", len(entities))


class HdgBoilerSensor(HdgNodeEntity, SensorEntity):
    """Represents an HDG Bavaria Boiler sensor entity."""

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        entity_description: SensorEntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """Initialize the HDG Boiler sensor entity."""
        super().__init__(coordinator, entity_description, entity_definition)
        self._attr_native_value = None
        # Set initial state, coordinator data should be available after first refresh
        self._update_sensor_state()
        _LIFECYCLE_LOGGER.debug("HdgBoilerSensor %s: Initialized.", self.entity_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_sensor_state()
        super()._handle_coordinator_update()

    def _update_sensor_state(self) -> None:
        """Update the sensor's state from the coordinator's data."""
        if not self.available:
            self._attr_native_value = None
            return

        raw_value = self.coordinator.data.get(self._node_id)
        parsed_value = parse_sensor_value(
            raw_value=raw_value,
            entity_definition=cast(dict[str, Any], self._entity_definition),
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
            raw_value,
            parsed_value,
        )
