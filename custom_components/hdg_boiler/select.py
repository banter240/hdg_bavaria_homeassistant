"""Select platform for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.1.20"

import logging


from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    ENTITY_DETAIL_LOGGER_NAME,
    LIFECYCLE_LOGGER_NAME,
)
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
    """Set up the HDG Bavaria Boiler select entities.

    This function is called by Home Assistant during the setup of the integration.
    It iterates through `SENSOR_DEFINITIONS`, identifies entities configured for
    the 'select' platform, validates their definitions, and creates
    `HdgBoilerSelect` instances for them.
    """
    integration_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: HdgDataUpdateCoordinator = integration_data["coordinator"]
    hdg_entity_registry: HdgEntityRegistry = integration_data["hdg_entity_registry"]

    select_definitions = hdg_entity_registry.get_entities_for_platform("select")

    entities_to_add = []
    for entity_key, entity_def in select_definitions.items():
        _ENTITY_DETAIL_LOGGER.debug(
            "Preparing HDG select for translation_key: %s (HDG Node ID: %s)",
            entity_key,
            entity_def.get("hdg_node_id", "N/A"),
        )
        description = create_entity_description(
            SelectEntityDescription, entity_key, entity_def
        )
        entities_to_add.append(HdgBoilerSelect(coordinator, description, entity_def))

    if entities_to_add:
        async_add_entities(entities_to_add)
        hdg_entity_registry.increment_added_entity_count("select", len(entities_to_add))
        _LIFECYCLE_LOGGER.info(
            "Added %s HDG Bavaria select entities.", len(entities_to_add)
        )
    else:
        _LIFECYCLE_LOGGER.info("No select entities to add from SENSOR_DEFINITIONS.")


class HdgBoilerSelect(HdgNodeEntity, SelectEntity):
    """Representation of a HDG Bavaria Boiler Select entity."""

    entity_description: SelectEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        description: SelectEntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """Initialize the HDG Boiler select entity."""
        super().__init__(coordinator, description, entity_definition)
        # The options for the select entity are the raw internal keys from definitions.py
        # Home Assistant's translation system will handle mapping these keys to
        # translated strings in the UI via the translation files (e.g., de.json, en.json).
        self._attr_options = entity_definition.get("options", [])
        _LIFECYCLE_LOGGER.debug("HdgBoilerSelect %s: Initialized.", self.entity_id)

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option (raw internal key)."""
        # The current option is the raw value from the coordinator's data.
        # Home Assistant will use the translation_key and the 'state' mapping
        # in the translation files to display the human-readable translated value.
        raw_value = self.coordinator.data.get(self._node_id)
        return None if raw_value is None else str(raw_value)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option. 'option' is the raw internal key."""
        # The 'option' received here is already the raw internal key (e.g., "NORMAL", "PARTY")
        # because self._attr_options was populated with these raw keys.
        # We directly pass this raw key to the coordinator to set the node value.
        if option in self.options:
            # Optimistically update the state in the coordinator's data and trigger a UI update
            # This makes the UI immediately responsive to the user's selection.
            self.coordinator.data[self._node_id] = option
            self.async_write_ha_state()

            await self.coordinator.async_set_node_value(
                self._node_id, option, self.entity_id
            )
        else:
            _LOGGER.error(
                "Invalid option '%s' selected for %s. Valid options are: %s",
                option,
                self.entity_id,
                self._attr_options,
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
        _ENTITY_DETAIL_LOGGER.debug(
            "Entity %s (Node ID: %s): Updated state. Current Option: '%s'",
            self.entity_id,
            self._node_id,
            self.current_option,
        )
