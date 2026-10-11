"""Sensor platform for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__all__ = ["async_setup_entry"]

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import HdgDataUpdateCoordinator
from .const import HDG_DATETIME_SPECIAL_TEXT
from .entity import HdgNodeEntity
from .helpers.entity_utils import async_setup_hdg_platform
from .helpers.logging_utils import get_redacted_logger
from .models import SensorDefinition

_LIFECYCLE_LOGGER = get_redacted_logger(__name__)


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
    def device_class(self) -> SensorDeviceClass | None:
        """Return the device class, unless the value is the over-7-days text."""
        raw = (
            self.coordinator.data.get(self._node_id) if self.coordinator.data else None
        )
        if isinstance(raw, str) and HDG_DATETIME_SPECIAL_TEXT in raw.lower():
            return None
        return super().device_class

    @property
    def native_value(self) -> Any:
        """Return the parsed sensor value from coordinator data."""
        return self._get_value() if self.available else None
