"""Provides number entities for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__all__ = ["async_setup_entry"]

import logging
import math

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import USER_ACTION_LOGGER_NAME
from .coordinator import HdgDataUpdateCoordinator
from .entity import HdgNodeEntity
from .helpers.entity_utils import async_setup_hdg_platform
from .models import SensorDefinition

_USER_ACTION_LOGGER = logging.getLogger(USER_ACTION_LOGGER_NAME)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HDG Bavaria Boiler number entities from a config entry."""
    await async_setup_hdg_platform(
        hass, entry, async_add_entities, "number", HdgBoilerNumber
    )


class HdgBoilerNumber(HdgNodeEntity, NumberEntity):
    """Represents a number entity for an HDG Bavaria Boiler."""

    entity_description: NumberEntityDescription

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        entity_description: EntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """Initialize the HDG Boiler number entity."""
        super().__init__(coordinator, entity_description, entity_definition)

    @property
    def native_value(self) -> float | int | None:
        """Return the current value, preferring in-flight optimistic state."""
        if not self.available:
            return None
        if (opt := self.coordinator.get_optimistic_value(self._node_id)) is not None:
            try:
                val = float(opt)
                return int(math.floor(val + 0.5)) if self.native_step == 1.0 else val
            except (ValueError, TypeError):
                pass
        parsed = self._get_value()
        if not isinstance(parsed, int | float):
            return None
        return (
            int(math.floor(parsed + 0.5)) if self.native_step == 1.0 else float(parsed)
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the new native value and initiate a debounced API call."""
        _USER_ACTION_LOGGER.debug(
            "%s: async_set_native_value called with: %s", self.entity_id, value
        )
        rounded = math.floor(value + 0.5) if self.native_step == 1.0 else value
        await self._set_value(str(rounded))
