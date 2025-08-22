"""Provides number entities for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.2.0"
__all__ = ["async_setup_entry"]

import logging
from typing import Any, cast

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    ENTITY_DETAIL_LOGGER_NAME,
    LIFECYCLE_LOGGER_NAME,
    USER_ACTION_LOGGER_NAME,
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
_USER_ACTION_LOGGER = logging.getLogger(USER_ACTION_LOGGER_NAME)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HDG Bavaria Boiler number entities from a config entry."""
    integration_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HdgDataUpdateCoordinator = integration_data["coordinator"]
    hdg_entity_registry: HdgEntityRegistry = integration_data["hdg_entity_registry"]

    number_definitions = hdg_entity_registry.get_entities_for_platform("number")
    if entities := [
        HdgBoilerNumber(
            coordinator,
            cast(
                NumberEntityDescription,
                create_entity_description("number", key, entity_def),
            ),
            entity_def,
        )
        for key, entity_def in number_definitions.items()
    ]:
        async_add_entities(entities)
        hdg_entity_registry.increment_added_entity_count("number", len(entities))
        _LIFECYCLE_LOGGER.info("Added %d HDG number entities.", len(entities))


class HdgBoilerNumber(HdgNodeEntity, NumberEntity):
    """Represents a number entity for an HDG Bavaria Boiler."""

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        entity_description: NumberEntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """Initialize the HDG Boiler number entity."""
        super().__init__(coordinator, entity_description, entity_definition)
        self._attr_native_value: float | None = None
        self._update_number_state()
        _LIFECYCLE_LOGGER.debug("HdgBoilerNumber %s: Initialized.", self.entity_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data updates from the coordinator."""
        self._update_number_state()
        super()._handle_coordinator_update()

    def _handle_optimistic_update(self) -> bool:
        """Handle the optimistic update logic.

        Returns True if the optimistic value should be kept, False otherwise.
        """
        optimistic_value = self.coordinator._setter_state["optimistic_values"].get(
            self._node_id
        )
        if optimistic_value is None:
            return False

        raw_value = self.coordinator.data.get(self._node_id)
        parsed_value = self._parse_value(raw_value)

        if parsed_value != optimistic_value:
            return True

        self.coordinator._setter_state["optimistic_values"].pop(self._node_id, None)
        self.coordinator._setter_state["optimistic_times"].pop(self._node_id, None)
        return False

    def _update_number_state(self) -> None:
        """Update the entity's internal state from coordinator data."""
        if self._handle_optimistic_update():
            return

        if not self.available:
            self._attr_native_value = None
            return

        raw_value = self.coordinator.data.get(self._node_id)
        parsed_value = self._parse_value(raw_value)
        self._attr_native_value = parsed_value

    def _parse_value(self, raw_value: Any) -> float | int | None:
        """Parse the raw value from the API into a float or int."""
        parsed = parse_sensor_value(
            raw_value=raw_value,
            entity_definition=cast(dict[str, Any], self._entity_definition),
            node_id_for_log=self._node_id,
            entity_id_for_log=self.entity_id,
        )
        if not isinstance(parsed, int | float):
            if parsed is not None:
                _LOGGER.warning(
                    "%s: Parsed value '%s' for node %s is not a number.",
                    self.entity_id,
                    parsed,
                    self._node_id,
                )
            return None
        return int(parsed) if self.native_step == 1.0 else float(parsed)

    async def async_set_native_value(self, value: float) -> None:
        """Set the new native value and initiate a debounced API call."""
        _USER_ACTION_LOGGER.debug(
            "%s: async_set_native_value called with: %s", self.entity_id, value
        )

        self._attr_native_value = int(value) if self.native_step == 1.0 else value
        self.async_write_ha_state()

        await self.coordinator.async_set_node_value(
            node_id=self._node_id,
            value=str(self._attr_native_value),
            entity_name_for_log=self.name or self.entity_id,
            debounce_delay=0.5,
        )
