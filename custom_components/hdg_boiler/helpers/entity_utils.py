"""Utility functions for creating Home Assistant entities.

This module centralizes the logic for creating entity descriptions and entities,
ensuring consistency and adhering to the DRY (Don't Repeat Yourself) principle
across different platforms (sensor, number, etc.).
"""

from __future__ import annotations

__version__ = "0.1.1"

import logging

from typing import cast

from homeassistant.components.number import NumberEntityDescription, NumberMode
from homeassistant.components.sensor import SensorEntityDescription

from ..models import SensorDefinition
from ..const import DOMAIN, ENTITY_DETAIL_LOGGER_NAME

_LOGGER = logging.getLogger(DOMAIN)
_ENTITY_DETAIL_LOGGER = logging.getLogger(ENTITY_DETAIL_LOGGER_NAME)


def create_entity_description[T: (SensorEntityDescription, NumberEntityDescription)](
    description_class: type[T],
    translation_key: str,
    entity_definition: SensorDefinition,
    native_step: float | None = None,
) -> T:
    """Create a sensor or number entity description from a node definition.

    Args:
        description_class: The HA entity description class (e.g., SensorEntityDescription).
        translation_key: The base translation key for the entity.
        entity_definition: The detailed definition for the entity.
        native_step: The step value for number entities, passed explicitly.

    Returns:
        A fully populated entity description instance.

    """
    # Common attributes for both Sensor and Number entities
    description_kwargs = {
        "key": translation_key,
        "name": None,  # Use translation key for localization
        "translation_key": translation_key,
        "icon": entity_definition.get("icon"),
        "device_class": entity_definition.get("device_class"),
        "native_unit_of_measurement": entity_definition.get(
            "native_unit_of_measurement"
        ),
        "entity_category": entity_definition.get("entity_category"),
    }

    # Platform-specific attributes
    if description_class is SensorEntityDescription:
        description_kwargs["state_class"] = entity_definition.get("state_class")
    elif description_class is NumberEntityDescription:
        min_val = cast(float, entity_definition.get("setter_min_val"))
        max_val = cast(float, entity_definition.get("setter_max_val"))

        description_kwargs |= {
            "native_min_value": min_val,
            "native_max_value": max_val,
            "native_step": native_step,
            "mode": NumberMode.BOX,
        }

    # Filter out None values to avoid overriding defaults in the description class
    filtered_kwargs = {k: v for k, v in description_kwargs.items() if v is not None}

    return description_class(**filtered_kwargs)
