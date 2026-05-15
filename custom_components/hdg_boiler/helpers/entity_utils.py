"""Utility functions for creating Home Assistant entities.

This module centralizes the logic for creating entity descriptions, ensuring
consistency and adhering to the DRY (Don't Repeat Yourself) principle across
different platforms (sensor, number, select, etc.).
"""

from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.number import NumberEntityDescription, NumberMode
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DOMAIN, LIFECYCLE_LOGGER_NAME
from ..models import SensorDefinition

if TYPE_CHECKING:
    from ..entity import HdgNodeEntity

_LOGGER = logging.getLogger(DOMAIN)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)

__all__ = ["async_setup_hdg_platform", "create_entity_description"]


def create_entity_description(
    platform: str, translation_key: str, entity_definition: SensorDefinition
) -> EntityDescription:
    """Create a platform-specific EntityDescription from a sensor definition."""
    base_kwargs = {
        "key": translation_key,
        "name": None,  # Use translation key for localization
        "translation_key": translation_key,
        "icon": entity_definition.get("icon"),
        "device_class": entity_definition.get("ha_device_class"),
        "native_unit_of_measurement": entity_definition.get(
            "ha_native_unit_of_measurement"
        ),
    }
    if entity_category := entity_definition.get("entity_category"):
        base_kwargs["entity_category"] = entity_category

    platform_specific_kwargs: dict[str, Any] = {}
    description_class: type[EntityDescription]

    if platform == "sensor":
        platform_specific_kwargs["state_class"] = entity_definition.get(
            "ha_state_class"
        )
        description_class = SensorEntityDescription
    elif platform == "number":
        platform_specific_kwargs |= {
            "native_min_value": cast(float, entity_definition.get("setter_min_val")),
            "native_max_value": cast(float, entity_definition.get("setter_max_val")),
            "native_step": entity_definition.get("setter_step", 1.0),
            "mode": NumberMode.BOX,
        }
        description_class = NumberEntityDescription
    elif platform == "select":
        platform_specific_kwargs["options"] = entity_definition.get("options", [])
        description_class = SelectEntityDescription
    else:
        raise ValueError(f"Unsupported platform for entity description: {platform}")

    final_kwargs = {
        k: v
        for k, v in (base_kwargs | platform_specific_kwargs).items()
        if v is not None
    }
    return description_class(**final_kwargs)


async def async_setup_hdg_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    platform: str,
    entity_class: type[HdgNodeEntity],
) -> None:
    """Set up entities for an HDG Bavaria platform.

    Centralises the boilerplate that every platform's async_setup_entry would
    otherwise duplicate: coordinator/registry lookup, entity list comprehension,
    add_entities call, counter increment, and lifecycle log.
    """
    from ..coordinator import HdgDataUpdateCoordinator  # local to avoid circular
    from ..registry import HdgEntityRegistry

    integration_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HdgDataUpdateCoordinator = integration_data["coordinator"]
    hdg_entity_registry: HdgEntityRegistry = integration_data["hdg_entity_registry"]

    definitions = hdg_entity_registry.get_entities_for_platform(platform)
    if entities := [
        entity_class(
            coordinator,
            create_entity_description(platform, key, entity_def),
            entity_def,
        )
        for key, entity_def in definitions.items()
    ]:
        async_add_entities(entities)
        hdg_entity_registry.increment_added_entity_count(platform, len(entities))
        _LIFECYCLE_LOGGER.info(
            "Added %d HDG Bavaria %s entities.", len(entities), platform
        )
