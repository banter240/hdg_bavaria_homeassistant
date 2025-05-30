"""
Platform for number entities for the HDG Bavaria Boiler integration.

This module creates and manages number entities, allowing users to view and
modify numeric settings on their HDG Bavaria boiler system.
"""

__version__ = "0.8.1"

import logging
import re
from typing import Any, Optional, cast, Union
import asyncio

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, HassJob
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    SENSOR_DEFINITIONS,
    NUMBER_SET_VALUE_DEBOUNCE_DELAY_S,
    SensorDefinition,
)
from .coordinator import HdgDataUpdateCoordinator
from .entity import HdgNodeEntity
from .api import (
    HdgApiClient,
    HdgApiError,
)

_LOGGER = logging.getLogger(DOMAIN)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HDG Bavaria Boiler number entities from a configuration entry."""
    integration_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HdgDataUpdateCoordinator = integration_data["coordinator"]
    api_client: HdgApiClient = integration_data["api_client"]

    number_entities: list[HdgBoilerNumber] = []

    for translation_key, entity_definition_dict in SENSOR_DEFINITIONS.items():
        entity_def = cast(SensorDefinition, entity_definition_dict)

        if entity_def.get("ha_platform") != "number":
            continue

        hdg_node_id_with_suffix = entity_def.get("hdg_node_id")
        if not hdg_node_id_with_suffix:
            _LOGGER.warning(
                f"Skipping number entity for translation_key '{translation_key}': "
                f"missing 'hdg_node_id' in SENSOR_DEFINITIONS."
            )
            continue

        # Base HDG node ID (without suffix) is used for fetching and setting data.
        raw_hdg_node_id = hdg_node_id_with_suffix.rstrip("TUVWXY")

        # Settable number entities require 'setter_type' and other 'setter_*' parameters.
        if not entity_def.get("setter_type"):
            _LOGGER.warning(
                f"Skipping number entity for translation_key '{translation_key}' (HDG Node {raw_hdg_node_id}): "
                f"Missing 'setter_type' or other required setter parameters "
                f"in SENSOR_DEFINITIONS."
            )
            continue

        min_val = float(entity_def.get("setter_min_val", 0.0))
        max_val = float(entity_def.get("setter_max_val", 100.0))
        step_val_config = entity_def.get("setter_step", 1.0)

        # HA's NumberEntity requires a non-zero step.
        # Default to 0.1 for floats, 1.0 for ints if SENSOR_DEFINITIONS step is 0.
        setter_type_for_step_check = entity_def.get("setter_type", "").lower()
        step_val = (
            float(step_val_config)
            if float(step_val_config) != 0.0
            else (0.1 if "float" in setter_type_for_step_check else 1.0)
        )

        description = NumberEntityDescription(
            key=translation_key,
            name=None,
            translation_key=translation_key,
            icon=entity_def.get("icon"),
            device_class=entity_def.get("ha_device_class"),
            native_unit_of_measurement=entity_def.get("ha_native_unit_of_measurement"),
            entity_category=entity_def.get("entity_category"),
            native_min_value=min_val,
            native_max_value=max_val,
            native_step=step_val,
            mode=NumberMode.BOX,
        )

        number_entities.append(HdgBoilerNumber(coordinator, api_client, description, entity_def))
        _LOGGER.debug(
            f"Preparing HDG number entity for translation_key: {translation_key} "
            f"(HDG Node for API set: {raw_hdg_node_id}, SENSOR_DEF Node ID: {hdg_node_id_with_suffix})"
        )

    if number_entities:
        async_add_entities(number_entities)
        _LOGGER.info(f"Added {len(number_entities)} HDG Bavaria number entities.")
    else:
        _LOGGER.info(
            "No number entities to add from SENSOR_DEFINITIONS with required setter parameters."
        )


class HdgBoilerNumber(HdgNodeEntity, NumberEntity):
    """
    Represents an HDG Bavaria Boiler number entity.
    Handles state updates and debounces API calls for setting values.
    """

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        api_client: HdgApiClient,
        entity_description: NumberEntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """Initialize the HDG Boiler number entity."""
        hdg_api_node_id_from_def = entity_definition["hdg_node_id"]
        super().__init__(coordinator, hdg_api_node_id_from_def.rstrip("TUVWXY"), entity_definition)

        self.entity_description = entity_description
        self._api_client = api_client  # Stored for potential future direct interactions.

        # Attributes for debouncing set value API calls.
        self._pending_api_call_timer: Optional[asyncio.TimerHandle] = None
        self._pending_value_to_set: Optional[float] = None  # Value from HA UI is float

        self._attr_native_value = None  # Can be int or float after parsing
        self._update_number_state()

        _LOGGER.debug(
            f"HdgBoilerNumber {self.entity_description.key}: Initialized. "
            f"Node ID: {self._node_id}, Min: {self.native_min_value}, Max: {self.native_max_value}, Step: {self.native_step}"
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data updates from the coordinator."""
        self._update_number_state()
        super()._handle_coordinator_update()

    def _update_number_state(self) -> None:
        """Update the entity's internal state from coordinator data."""
        self._attr_available = super().available

        if not self._attr_available:
            self._attr_native_value = None
            return

        raw_value_text = self.coordinator.data.get(self._node_id)
        self._attr_native_value = self._parse_value(raw_value_text)

    def _parse_value(self, raw_value_text: Optional[str]) -> Optional[Union[int, float]]:
        """
        Parse the raw string value from the API into an int or float.
        Handles potential non-numeric characters or units.
        Considers 'setter_type' from entity_definition to return int or float.
        """
        if raw_value_text is None:
            return None

        cleaned_value = raw_value_text.strip()
        if not cleaned_value:
            return None

        # Defensive check: if raw_value_text is already numeric (though API usually sends strings)
        if isinstance(raw_value_text, (int, float)):
            if self._entity_definition.get("setter_type") == "int" and float(raw_value_text) == int(
                raw_value_text
            ):
                return int(raw_value_text)
            return float(raw_value_text)

        # Main parsing logic for string inputs.
        try:
            # Regex to extract numeric part (int/float) from strings like "21.5 °C".
            match = re.search(r"([-+]?\d*\.?\d+)", cleaned_value)
            if match:
                numeric_part_str = match.group(1)
                setter_type = self._entity_definition.get("setter_type")

                if setter_type == "int":
                    # Convert to float first to handle inputs like "21.0", then to int.
                    return int(float(numeric_part_str))
                # For "float1", "float2", or if setter_type is not "int", parse as float.
                return float(numeric_part_str)

            _LOGGER.debug(
                f"Could not extract numeric part for {self.entity_id} from: '{cleaned_value}'"
            )
            return None
        except ValueError:
            _LOGGER.warning(
                f"Could not parse number value for {self.entity_id} from text: '{cleaned_value}'"
            )
            return None

    async def async_set_native_value(self, value: float) -> None:
        """
        Update the number entity's value, initiating a debounced API call.
        Home Assistant's NumberEntity base class provides `value` as float.
        """
        _LOGGER.debug(
            f"async_set_native_value called for {self.entity_id} with value {value}. "
            f"Debouncing for {NUMBER_SET_VALUE_DEBOUNCE_DELAY_S}s."
        )
        self._pending_value_to_set = value

        if self._pending_api_call_timer:
            self._pending_api_call_timer()  # Cancel existing timer
            _LOGGER.debug(f"Cancelled existing API call timer for {self.entity_id}.")

        # Schedule the API call after debounce delay.
        self._pending_api_call_timer = async_call_later(
            self.hass,
            NUMBER_SET_VALUE_DEBOUNCE_DELAY_S,
            HassJob(
                self._execute_set_value_api_call,
                name=f"HdgBoilerNumber_SetValue_{self.entity_id}",
            ),
        )

    async def _execute_set_value_api_call(self, *args: Any) -> None:
        """
        Execute the API call to set the node value after debounce.
        Formats value based on 'setter_type' and calls coordinator.
        """
        if self._pending_value_to_set is None:
            _LOGGER.debug(f"No pending value to set for {self.entity_id}. Skipping API call.")
            return

        # Validate and convert the pending value (e.g., from UI input).
        # self._pending_value_to_set is expected to be a float from async_set_native_value.
        try:
            value_to_send_numeric = float(self._pending_value_to_set)
        except (ValueError, TypeError) as e:  # Should not happen if HA sends float
            _LOGGER.error(
                f"Invalid value '{self._pending_value_to_set}' (type: {type(self._pending_value_to_set)}) "
                f"cannot be set for {self.entity_id}. Error: {e}. Aborting API call."
            )
            self._pending_api_call_timer = None
            self._pending_value_to_set = None
            return

        _LOGGER.info(
            f"Executing debounced API call for {self.entity_id} (Node ID: {self._node_id}) with value {value_to_send_numeric}"
        )

        node_type = self._entity_definition.get("setter_type")
        api_value_to_send_str: str

        # Format numeric value to string based on HDG API expectation.
        if node_type == "int":
            api_value_to_send_str = str(int(round(value_to_send_numeric)))
        elif node_type == "float1":
            api_value_to_send_str = f"{value_to_send_numeric:.1f}".replace(",", ".")
        elif node_type == "float2":
            api_value_to_send_str = f"{value_to_send_numeric:.2f}".replace(",", ".")
        else:  # Default if type is unknown or generic float.
            api_value_to_send_str = str(value_to_send_numeric)

        try:
            # Delegate API call to coordinator, which handles "if_changed" logic.
            success = await self.coordinator.async_set_node_value_if_changed(
                node_id=self._node_id,
                new_value_to_set=api_value_to_send_str,
                entity_name_for_log=self.name or self.entity_id,
            )
            if not success:
                _LOGGER.error(
                    f"Failed to set value for {self.name or self.entity_id} (API call reported failure by coordinator)."
                )
                raise HomeAssistantError(
                    f"Failed to set value for {self.name or self.entity_id} (API call reported failure by coordinator)."
                )
        except HdgApiError as err:
            _LOGGER.error(f"API error setting value for {self.entity_id}: {err}")
            raise HomeAssistantError(
                f"API error setting value for {self.name or self.entity_id}: {err}"
            ) from err
        except Exception as err:
            _LOGGER.exception(f"Unexpected error setting value for {self.entity_id}: {err}")
            raise HomeAssistantError(
                f"Unexpected error setting value for {self.name or self.entity_id}: {err}"
            ) from err
        finally:
            # Clear pending state after API call attempt.
            self._pending_api_call_timer = None
            self._pending_value_to_set = None
