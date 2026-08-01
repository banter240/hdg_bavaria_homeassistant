"""Sensor platform for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__all__ = ["async_setup_entry"]

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import HdgDataUpdateCoordinator
from .entity import HdgNodeEntity
from .helpers.entity_utils import async_setup_hdg_platform
from .models import SensorDefinition

_LIFECYCLE_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HDG Bavaria sensor entities from a config entry."""
    await async_setup_hdg_platform(
        hass, entry, async_add_entities, "sensor", HdgBoilerSensor
    )


class HdgBoilerSensor(HdgNodeEntity, SensorEntity):
    """Represents an HDG Bavaria Boiler sensor entity."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        entity_description: EntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """Initialize the HDG Boiler sensor entity."""
        super().__init__(coordinator, entity_description, entity_definition)

    @property
    def native_value(self) -> Any:
        """Return the parsed sensor value from coordinator data."""
        return self._get_value() if self.available else None
