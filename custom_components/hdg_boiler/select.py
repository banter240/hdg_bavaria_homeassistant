"""Select platform for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__all__ = ["async_setup_entry"]

import logging

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, USER_ACTION_LOGGER_NAME
from .coordinator import HdgDataUpdateCoordinator
from .entity import HdgNodeEntity
from .helpers.entity_utils import async_setup_hdg_platform
from .models import SensorDefinition

_LOGGER = logging.getLogger(DOMAIN)
_USER_ACTION_LOGGER = logging.getLogger(USER_ACTION_LOGGER_NAME)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the HDG Bavaria Boiler select entities."""
    await async_setup_hdg_platform(
        hass, entry, async_add_entities, "select", HdgBoilerSelect
    )


class HdgBoilerSelect(HdgNodeEntity, SelectEntity):
    """Representation of a HDG Bavaria Boiler Select entity."""

    entity_description: SelectEntityDescription

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        description: EntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """Initialize the HDG Boiler select entity."""
        super().__init__(coordinator, description, entity_definition)
        self._attr_options = entity_definition.get("options", [])

    @property
    def current_option(self) -> str | None:
        """Return the current option, preferring optimistic state while a SET is in-flight."""
        if not self.available:
            return None
        uppercase = self._entity_definition.get("uppercase_value")
        if (opt := self.coordinator.get_optimistic_value(self._node_id)) is not None:
            return str(opt).lower() if uppercase else str(opt)
        val = self._get_value()
        if val is None:
            return None
        processed = str(val)
        return processed.lower() if uppercase else processed

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in (self.options or []):
            _LOGGER.error(
                "Invalid option '%s' for %s. Valid: %s",
                option,
                self.entity_id,
                self.options,
            )
            return
        _USER_ACTION_LOGGER.debug(
            "%s: async_select_option called with: %s", self.entity_id, option
        )
        value_to_send = (
            option.upper() if self._entity_definition.get("uppercase_value") else option
        )
        await self._set_value(value_to_send)
