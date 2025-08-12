"""Select platform for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "1.0.1"
__all__ = ["async_setup_entry"]

import logging
import time
from typing import cast

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ENTITY_DETAIL_LOGGER_NAME, LIFECYCLE_LOGGER_NAME
from .coordinator import HdgDataUpdateCoordinator
from .entity import HdgNodeEntity
from .helpers.entity_utils import create_entity_description
from .models import SensorDefinition
from .registry import HdgEntityRegistry

_LOGGER = logging.getLogger(DOMAIN)
_ENTITY_DETAIL_LOGGER = logging.getLogger(ENTITY_DETAIL_LOGGER_NAME)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the HDG Bavaria Boiler select entities."""
    integration_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: HdgDataUpdateCoordinator = integration_data["coordinator"]
    hdg_entity_registry: HdgEntityRegistry = integration_data["hdg_entity_registry"]

    select_definitions = hdg_entity_registry.get_entities_for_platform("select")
    if entities := [
        HdgBoilerSelect(
            coordinator,
            create_entity_description("select", key, entity_def),
            entity_def,
        )
        for key, entity_def in select_definitions.items()
    ]:
        async_add_entities(entities)
        hdg_entity_registry.increment_added_entity_count("select", len(entities))
        _LIFECYCLE_LOGGER.info("Added %d HDG Bavaria select entities.", len(entities))


class HdgBoilerSelect(HdgNodeEntity, SelectEntity):
    """Representation of a HDG Bavaria Boiler Select entity."""

    entity_description: SelectEntityDescription

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        description: SelectEntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """Initialize the HDG Boiler select entity."""
        super().__init__(coordinator, description, entity_definition)
        self._attr_options = entity_definition.get("options", [])
        self._attr_translation_key = entity_definition.get("translation_key")
        _LIFECYCLE_LOGGER.debug("HdgBoilerSelect %s: Initialized.", self.entity_id)

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        optimistic_time = self.coordinator._setter_state["optimistic_times"].get(
            self._node_id
        )
        if optimistic_time and (time.monotonic() - optimistic_time) < 30:
            optimistic_value = self.coordinator._setter_state["optimistic_values"].get(
                self._node_id
            )
            if optimistic_value is not None:
                str_optimistic_value = str(cast(str, optimistic_value))
                _LOGGER.debug(
                    "[%s] Using optimistic value '%s'",
                    self.entity_description.key,
                    str_optimistic_value,
                )
                return str_optimistic_value

        # For select entities, the state from the coordinator is the raw enum key.
        # Home Assistant handles the translation to the display value automatically.
        if self.coordinator.data and (
            raw_value := self.coordinator.data.get(self._node_id)
        ):
            if raw_value is not None:
                return str(cast(str | int | float, raw_value))
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in self.options:
            _LOGGER.error(
                "Invalid option '%s' for %s. Valid: %s",
                option,
                self.entity_id,
                self.options,
            )
            return

        # This call handles optimistic state and debouncing centrally.
        await self.coordinator.async_set_node_value(
            self._node_id,
            option,
            self.entity_id,
            2.0,  # Using a 2s debounce
        )
        # Immediately update the UI to reflect the user's choice.
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # When the coordinator gets new data, this entity is re-rendered,
        # and the `current_option` property will correctly reflect the new state.
        self.async_write_ha_state()
        _ENTITY_DETAIL_LOGGER.debug(
            "Entity %s (Node ID: %s): Coordinator updated. Current Option: '%s'",
            self.entity_id,
            self._node_id,
            self.current_option,
        )
