"""Provides number entities for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__all__ = ["async_setup_entry"]

import math

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import HdgDataUpdateCoordinator
from .entity import HdgNodeEntity
from .helpers.entity_utils import async_setup_hdg_platform
from .helpers.logging_utils import _USER_ACTION_LOGGER
from .models import SensorDefinition


def _round_half_up(value: float) -> int:
    """Round half up via floor(x + 0.5).

    Deliberate: avoids banker's rounding from round().
    """
    return math.floor(value + 0.5)


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
                return _round_half_up(val) if self.native_step == 1.0 else val
            except (ValueError, TypeError):
                pass
        parsed = self._get_value()
        if not isinstance(parsed, int | float):
            return None
        return (
            _round_half_up(float(parsed)) if self.native_step == 1.0 else float(parsed)
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set the new native value and initiate a debounced API call."""
        _USER_ACTION_LOGGER.debug(
            "%s: async_set_native_value called with: %s", self.entity_id, value
        )
        rounded = _round_half_up(value) if self.native_step == 1.0 else value
        await self._set_value(str(rounded))
