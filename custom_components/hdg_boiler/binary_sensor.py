"""Binary sensor platform for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__all__ = ["async_setup_entry"]

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import HDG_UNAVAILABLE_STRINGS
from .entity import HdgNodeEntity
from .helpers.entity_utils import async_setup_hdg_platform
from .models import SensorDefinition

if TYPE_CHECKING:
    from .coordinator import HdgDataUpdateCoordinator


class HdgBoilerBinarySensor(HdgNodeEntity, BinarySensorEntity):
    """A boolean node value; the backend already delivers Python bools."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        entity_description: EntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """Initialize the binary sensor entity."""
        super().__init__(coordinator, entity_description, entity_definition)

    @property
    def is_on(self) -> bool | None:
        """Return the state; None marks an unread or unavailable node."""
        if not self.available:
            return None
        raw = self.coordinator.data.get(self._node_id)
        if isinstance(raw, str) and raw.lower().strip() in HDG_UNAVAILABLE_STRINGS:
            return None
        return bool(raw) if raw is not None else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HDG Bavaria binary sensor entities from a config entry."""
    await async_setup_hdg_platform(
        hass, entry, async_add_entities, "binary_sensor", HdgBoilerBinarySensor
    )
