"""Select platform for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.2.1"
__all__ = ["async_setup_entry"]

import logging

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ENTITY_DETAIL_LOGGER_NAME, LIFECYCLE_LOGGER_NAME
from .coordinator import HdgDataUpdateCoordinator
from .entity import HdgNodeEntity
from .helpers.entity_utils import create_select_entity_description
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
            create_select_entity_description(key, entity_def),
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
        _LIFECYCLE_LOGGER.debug("HdgBoilerSelect %s: Initialized.", self.entity_id)

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option, considering optimistic updates."""
        # Optimistic state is now managed centrally in the coordinator.
        # Check if an optimistic value for this entity exists and is recent.
        optimistic_value = self.coordinator._optimistic_set_values.get(self._node_id)
        if optimistic_value is not None:
            # To prevent using a stale optimistic value from a failed past request,
            # we could add a time check, but for now, we trust the coordinator clears it.
            return str(optimistic_value)

        # If no optimistic value, return the confirmed state from the last poll.
        raw_value = self.coordinator.data.get(self._node_id)
        return str(raw_value) if raw_value is not None else None

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

        # This call will handle the optimistic state and debouncing centrally.
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
        # The coordinator has received new data. This will clear any optimistic state
        # implicitly because `current_option` will fall back to `coordinator.data`.
        self.async_write_ha_state()
        _ENTITY_DETAIL_LOGGER.debug(
            "Entity %s (Node ID: %s): Coordinator updated. Current Option: '%s'",
            self.entity_id,
            self._node_id,
            self.current_option,
        )
