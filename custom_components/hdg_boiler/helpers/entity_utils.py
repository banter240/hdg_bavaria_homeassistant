"""Utility functions for creating Home Assistant entities.

This module centralizes the logic for creating entity descriptions, ensuring
consistency and adhering to the DRY (Don't Repeat Yourself) principle across
different platforms (sensor, number, select, etc.).
"""

from __future__ import annotations

__version__ = "0.2.1"

import logging
from typing import Any, cast

from homeassistant.components.number import NumberEntityDescription, NumberMode
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.sensor import SensorEntityDescription

from ..const import DOMAIN
from ..models import SensorDefinition

_LOGGER = logging.getLogger(DOMAIN)

__all__ = [
    "create_sensor_entity_description",
    "create_number_entity_description",
    "create_select_entity_description",
]


def _create_base_description_kwargs(
    translation_key: str, entity_definition: SensorDefinition
) -> dict[str, Any]:
    """Create a base dictionary of common attributes for entity descriptions."""
    kwargs = {
        "key": translation_key,
        "name": None,  # Use translation key for localization
        "translation_key": translation_key,
        "icon": entity_definition.get("icon"),
        "device_class": entity_definition.get("ha_device_class"),
        "native_unit_of_measurement": entity_definition.get(
            "ha_native_unit_of_measurement"
        ),
    }
    # EntityCategory is optional, only add it if it exists in the definition.
    if entity_category := entity_definition.get("entity_category"):
        kwargs["entity_category"] = entity_category
    return kwargs


def create_sensor_entity_description(
    translation_key: str, entity_definition: SensorDefinition
) -> SensorEntityDescription:
    """Create a SensorEntityDescription from a sensor definition."""
    description_kwargs = _create_base_description_kwargs(
        translation_key, entity_definition
    )
    description_kwargs["state_class"] = entity_definition.get("ha_state_class")

    filtered_kwargs = {k: v for k, v in description_kwargs.items() if v is not None}
    return SensorEntityDescription(**filtered_kwargs)


def create_number_entity_description(
    translation_key: str,
    entity_definition: SensorDefinition,
    native_step: float | None,
) -> NumberEntityDescription:
    """Create a NumberEntityDescription from a sensor definition."""
    description_kwargs = _create_base_description_kwargs(
        translation_key, entity_definition
    )
    min_val = cast(float, entity_definition.get("setter_min_val"))
    max_val = cast(float, entity_definition.get("setter_max_val"))

    description_kwargs |= {
        "native_min_value": min_val,
        "native_max_value": max_val,
        "native_step": native_step,
        "mode": NumberMode.BOX,
    }

    filtered_kwargs = {k: v for k, v in description_kwargs.items() if v is not None}
    return NumberEntityDescription(**filtered_kwargs)


def create_select_entity_description(
    translation_key: str, entity_definition: SensorDefinition
) -> SelectEntityDescription:
    """Create a SelectEntityDescription from a sensor definition."""
    description_kwargs = _create_base_description_kwargs(
        translation_key, entity_definition
    )
    description_kwargs["options"] = entity_definition.get("options", [])

    filtered_kwargs = {k: v for k, v in description_kwargs.items() if v is not None}
    return SelectEntityDescription(**filtered_kwargs)
