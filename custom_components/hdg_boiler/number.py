"""Provides number entities for the HDG Bavaria Boiler integration.

This module is responsible for creating and managing 'number' entities that
allow users to view and modify numeric settings on their HDG Bavaria boiler.
It handles state updates from the data coordinator and implements debouncing for API calls.
"""

from __future__ import annotations

__version__ = "0.1.3"

import logging
from typing import Any, cast

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    ENTITY_DETAIL_LOGGER_NAME,
    LIFECYCLE_LOGGER_NAME,
    USER_ACTION_LOGGER_NAME,
)
from .coordinator import HdgDataUpdateCoordinator
from .registry import HdgEntityRegistry
from .entity import HdgNodeEntity
from .helpers.entity_utils import create_entity_description
from .helpers.parsers import (
    parse_sensor_value,
)
from .helpers.string_utils import strip_hdg_node_suffix
from .helpers.validation_utils import (
    validate_value_range_and_step,
)
from .models import SensorDefinition

_LOGGER = logging.getLogger(DOMAIN)
_ENTITY_DETAIL_LOGGER = logging.getLogger(ENTITY_DETAIL_LOGGER_NAME)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)
_USER_ACTION_LOGGER = logging.getLogger(USER_ACTION_LOGGER_NAME)


class HdgBoilerNumber(HdgNodeEntity, NumberEntity):
    """Represents a number entity for an HDG Bavaria Boiler.

    This entity allows users to interact with numeric settings of the boiler,
    such as temperature setpoints. It handles optimistic UI updates, debounces
    API calls to prevent flooding the device, and validates input values.
    """

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        entity_description: NumberEntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """Initialize the HDG Boiler number entity.

        Args:
            coordinator: The data update coordinator.
            entity_description: The entity description for this number entity.
            entity_definition: Custom entity definition from SENSOR_DEFINITIONS.

        """
        self.entity_description = entity_description
        super().__init__(
            coordinator=coordinator,
            description=entity_description,
            entity_definition=entity_definition,
        )
        self._attr_native_value: int | float | None = None
        self._update_number_state()
        _LIFECYCLE_LOGGER.debug(
            # Use entity_description.key as self.entity_id might not be fully available at this stage.
            "HdgBoilerNumber %s: Initialized. Node ID: %s, Min: %s, Max: %s, Step: %s",
            self.entity_description.key or self._node_id,
            self._node_id,
            self.native_min_value,
            self.native_max_value,
            self.native_step,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data updates from the coordinator."""
        # This method is called when the coordinator has new data.
        # It updates the entity's state and then calls the superclass's
        # _handle_coordinator_update, which in turn calls async_write_ha_state.
        _ENTITY_DETAIL_LOGGER.debug(
            f"HdgBoilerNumber {self.entity_id}: _handle_coordinator_update called."
        )
        self._update_number_state()
        super()._handle_coordinator_update()
        _ENTITY_DETAIL_LOGGER.debug(
            f"HdgBoilerNumber {self.entity_id}: _handle_coordinator_update finished. New native_value: {self._attr_native_value}"
        )

    def _update_number_state(self) -> None:
        """Update the entity's internal state from coordinator data.

        This method implements logic to mitigate UI bouncing when a value is
        set optimistically and a poll with an older value arrives.
        """
        self._attr_available = super().available
        if not self._attr_available:
            self._attr_native_value = None
            _ENTITY_DETAIL_LOGGER.debug(
                f"HdgBoilerNumber {self.entity_id}: Not available, native_value set to None."
            )
            return

        raw_value_text = self.coordinator.data.get(self._node_id)
        parsed_value = self._parse_value(raw_value_text)

        self._attr_native_value = parsed_value

    def _parse_value(self, raw_value_text: str | None) -> int | float | None:
        """Parse the raw string value from the API into an int or float.

        Args:
            raw_value_text: The raw string value received from the API.

        Returns:
            The parsed numeric value (int or float), or None if parsing fails.

        """
        # Leverage the centralized parse_sensor_value from parsers.py
        # The entity_definition contains all necessary information for parsing.
        parsed_value = parse_sensor_value(
            raw_value_text=raw_value_text,
            entity_definition=cast(dict[str, Any], self._entity_definition),
            node_id_for_log=self._node_id,
            entity_id_for_log=self.entity_id,
            # No configured_timezone needed for number entities as they are numeric
        )
        # Ensure the parsed value is a number type as expected for NumberEntity
        if isinstance(parsed_value, int | float):
            return parsed_value
        if parsed_value is None:
            return None
        _LOGGER.warning(
            f"HdgBoilerNumber {self.entity_id}: Parsed value '{parsed_value}' (type: {type(parsed_value).__name__}) "
            f"for node {self._node_id} is not a number. Expected int or float."
        )
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the new native value and initiate a debounced API call.

        This method is called by Home Assistant when the user changes the value
        in the UI. It performs pre-validation, optimistically updates the UI,
        and schedules a debounced call to `_process_debounced_value` to
        handle the actual API communication.
        """
        _USER_ACTION_LOGGER.debug(
            f"HdgBoilerNumber {self.entity_id}: async_set_native_value called with UI value: {value} (type: {type(value)})"
        )

        # --- BEGIN Pre-validation ---
        try:
            min_val_def = self.native_min_value
            max_val_def = self.native_max_value
            node_step_def = self.native_step
            if (
                min_val_def is not None
                and max_val_def is not None
                and node_step_def is not None
            ):
                validate_value_range_and_step(
                    coerced_numeric_value=value,
                    min_val_def=min_val_def,
                    max_val_def=max_val_def,
                    node_step_def=node_step_def,
                    entity_name_for_log=self.name
                    if isinstance(self.name, str)
                    else self.entity_id,
                    node_id_str_for_log=self._node_id,
                    original_value_to_set_for_log=value,
                )
        except HomeAssistantError as e:
            _LOGGER.error(
                f"HdgBoilerNumber {self.entity_id}: Pre-validation failed for value {value}: {e}. Not setting value."
            )
            # Do not proceed with optimistic update or API call if validation fails.
            # UI should retain its previous valid state.
            return
        # --- END Pre-validation ---

        await self.coordinator.async_set_node_value(
            node_id=self._node_id,
            value=str(value),
            entity_name_for_log=self.name
            if isinstance(self.name, str)
            else self.entity_id,
        )


def _determine_ha_number_step_val(
    entity_def: SensorDefinition,
    translation_key: str,
    raw_hdg_node_id: str,
) -> float | None:
    """Determine the `native_step` for the Home Assistant NumberEntity.

    This function calculates the appropriate step value for the number entity's UI
    based on the 'setter_step' and 'setter_type' defined in the entity_definition.
    It provides default step values if 'setter_step' is not explicitly defined or
    if it's set to 0.0 (which has special meaning for the API but needs a
    sensible UI step).

    """
    setter_type_for_step_default = (entity_def.get("setter_type") or "").strip().lower()
    raw_step_val_config = entity_def.get("setter_step")
    step_val: float

    if raw_step_val_config is None:
        step_val = 0.1 if setter_type_for_step_default in {"float1", "float2"} else 1.0
        _ENTITY_DETAIL_LOGGER.debug(
            f"'setter_step' not defined for translation_key '{translation_key}' (Node {raw_hdg_node_id}). "
            f"Detected setter_type '{setter_type_for_step_default}', defaulting HA NumberEntity step to {step_val}."
        )
        return step_val

    try:
        # Cast to Any first to satisfy mypy when raw_step_val_config is not None
        parsed_step_val_config = float(cast(Any, raw_step_val_config))
    except (ValueError, TypeError):
        _LOGGER.error(  # Keep as error
            f"Invalid 'setter_step' value '{raw_step_val_config}' in SENSOR_DEFINITIONS for translation_key '{translation_key}' (Node {raw_hdg_node_id}). "
            f"Must be a number. This entity will be skipped."
        )
        return None

    if parsed_step_val_config < 0.0:
        _LOGGER.error(  # Keep as error
            f"Invalid 'setter_step' value {parsed_step_val_config} (negative) in SENSOR_DEFINITIONS for translation_key '{translation_key}' (Node {raw_hdg_node_id}). "
            f"Step must be non-negative. This entity will be skipped."
        )
        return None
    if parsed_step_val_config == 0.0:
        step_val = 0.1 if setter_type_for_step_default in {"float1", "float2"} else 1.0
        _LOGGER.warning(  # Keep as warning
            f"[{translation_key}][{raw_hdg_node_id}] SENSOR_DEFINITIONS has 'setter_step' of 0.0. "
            f"Only 'setter_min_val' is valid for API calls. HA UI will use step {step_val}, potentially confusing users. "
            "Service calls will correctly enforce the 0.0 step logic (only min_value allowed)."
        )
        return step_val
    return parsed_step_val_config


def _create_number_entity_if_valid(
    translation_key: str,
    entity_def: SensorDefinition,
    coordinator: HdgDataUpdateCoordinator,
) -> HdgBoilerNumber | None:
    """Validate an entity definition and create an HdgBoilerNumber entity.

    This helper function checks if a given entity definition from `SENSOR_DEFINITIONS`
    is valid for creating an `HdgBoilerNumber` entity. It verifies the presence and
    correctness of required fields like `hdg_node_id`, `setter_type`, `setter_min_val`,
    `setter_max_val`, and calculates the `native_step`. If valid, it instantiates
    and returns an `HdgBoilerNumber` entity.
    """
    hdg_node_id_with_suffix = entity_def.get("hdg_node_id")
    if not isinstance(hdg_node_id_with_suffix, str) or not hdg_node_id_with_suffix:
        _LOGGER.warning(  # Keep as warning
            f"Skipping number entity for translation_key '{translation_key}': "
            f"missing or invalid 'hdg_node_id' (value: {hdg_node_id_with_suffix})."
        )
        return None
    raw_hdg_node_id = strip_hdg_node_suffix(hdg_node_id_with_suffix)

    setter_type = entity_def.get("setter_type")
    if not isinstance(setter_type, str) or not setter_type:
        _LOGGER.warning(  # Keep as warning
            f"Skipping number entity for translation_key '{translation_key}' (HDG Node {raw_hdg_node_id}): "
            f"Missing or invalid 'setter_type' (value: {setter_type})."
        )
        return None

    min_val_def = entity_def.get("setter_min_val")
    max_val_def = entity_def.get("setter_max_val")
    try:
        float(cast(float, min_val_def))
        float(cast(float, max_val_def))
    except (ValueError, TypeError) as e:
        _LOGGER.error(  # Keep as error
            f"Invalid 'setter_min_val' ('{min_val_def}') or 'setter_max_val' ('{max_val_def}') "
            f"in SENSOR_DEFINITIONS for '{translation_key}' (Node {raw_hdg_node_id}): {e}. "
            "Values must be numbers. This entity will be skipped."
        )
        return None

    ha_native_step_val = _determine_ha_number_step_val(
        entity_def, translation_key, raw_hdg_node_id
    )
    if ha_native_step_val is None:
        return None

    description = create_entity_description(
        description_class=NumberEntityDescription,
        translation_key=translation_key,
        entity_definition=entity_def,
        native_step=ha_native_step_val,
    )
    return HdgBoilerNumber(coordinator, description, entity_def)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HDG Bavaria Boiler number entities from a config entry.

    This function is called by Home Assistant during the setup of the integration.
    It iterates through `SENSOR_DEFINITIONS`, identifies entities configured for
    the 'number' platform, validates their definitions, and creates
    `HdgBoilerNumber` instances for them.
    """
    integration_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HdgDataUpdateCoordinator = integration_data["coordinator"]
    hdg_entity_registry: HdgEntityRegistry = integration_data["hdg_entity_registry"]

    number_entities: list[HdgBoilerNumber] = []
    number_definitions = hdg_entity_registry.get_entities_for_platform("number")

    for translation_key, entity_def in number_definitions.items():
        if entity := _create_number_entity_if_valid(
            translation_key, entity_def, coordinator
        ):
            number_entities.append(entity)

    if number_entities:
        async_add_entities(number_entities)
        hdg_entity_registry.increment_added_entity_count("number", len(number_entities))
        _LIFECYCLE_LOGGER.info("Added %s HDG number entities.", len(number_entities))
    else:
        _LIFECYCLE_LOGGER.info("No number entities to add from SENSOR_DEFINITIONS.")
