"""Utility functions for creating Home Assistant entities.

This module centralizes the logic for creating entity descriptions, ensuring
consistency and adhering to the DRY (Don't Repeat Yourself) principle across
different platforms (sensor, number, select, etc.).
"""

from __future__ import annotations

__version__ = "0.3.0"

import logging
from typing import Any, cast

from homeassistant.components.number import NumberEntityDescription, NumberMode
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.helpers.entity import EntityDescription

from ..const import DOMAIN
from ..models import SensorDefinition

_LOGGER = logging.getLogger(DOMAIN)

__all__ = ["create_entity_description"]


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
