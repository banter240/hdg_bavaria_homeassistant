"""
Platform for number entities for the HDG Bavaria Boiler integration.

This module creates and manages 'number' entities, enabling users to modify
numeric settings on their HDG Bavaria boiler. These entities handle state
updates from the data coordinator and implement debouncing for API calls
when setting new values to prevent overwhelming the boiler's API.
"""

__version__ = "0.8.31"

import logging
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

from .const import (
    DOMAIN,
    NUMBER_SET_VALUE_DEBOUNCE_DELAY_S,
)
from .definitions import (
    SensorDefinition,
    SENSOR_DEFINITIONS,
)
from .coordinator import HdgDataUpdateCoordinator
from .entity import HdgNodeEntity
from .api import HdgApiClient, HdgApiError
from .utils import (
    strip_hdg_node_suffix,
    parse_int_from_string,
    parse_float_from_string,
    format_value_for_api,  # Import the shared utility function
)

_LOGGER = logging.getLogger(DOMAIN)


# Note: HdgInvalidSetterTypeError is no longer needed here as format_value_for_api
# now resides in utils and raises ValueError. The calling code should handle ValueError.


class HdgBoilerNumber(HdgNodeEntity, NumberEntity):
    """
    Represents an HDG Bavaria Boiler number entity.

    This entity enables users to view and modify numeric settings on the boiler.
    It receives state updates from the HdgDataUpdateCoordinator and,
    when a user sets a new value, debounces the API call to avoid
    sending too many requests in rapid succession. The actual API call to
    set the value is delegated to the coordinator.
    """

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        api_client: HdgApiClient,  # Kept for potential future direct use, though set via coordinator
        entity_description: NumberEntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """
        Initialize the HDG Boiler number entity.

        Args:
            coordinator: The HdgDataUpdateCoordinator for managing entity data.
            api_client: The HdgApiClient instance (primarily for reference, as
                        set operations are managed through the coordinator).
            entity_description: Standard Home Assistant NumberEntityDescription.
            entity_definition: Custom entity definition from SENSOR_DEFINITIONS.
        """
        # Extract the raw HDG node ID from the definition, which might include a suffix.
        hdg_api_node_id_from_def = entity_definition["hdg_node_id"]
        # Initialize the base entity, stripping the suffix for the internal node_id.
        super().__init__(
            coordinator, strip_hdg_node_suffix(hdg_api_node_id_from_def), entity_definition
        )

        # Store the standard HA entity description and API client reference.
        self.entity_description = entity_description
        self._api_client = api_client  # Retained, though set operations go via coordinator.

        # Timer handle for debouncing set value calls.
        self._pending_api_call_timer: Optional[asyncio.TimerHandle] = None
        # Stores the latest value received by async_set_native_value that is pending to be queued.
        self._latest_value_to_queue: Any | None = None

        # Initialize the entity's native value. This will be populated by _update_number_state
        # during the first coordinator update and on subsequent updates.
        self._attr_native_value = None
        self._update_number_state()  # Perform an initial state update upon creation.

        _LOGGER.debug(
            f"HdgBoilerNumber {self.entity_description.key}: Initialized. "
            f"Node ID: {self._node_id}, Min: {self.native_min_value}, Max: {self.native_max_value}, Step: {self.native_step}"
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """
        Handle data updates from the coordinator.

        This callback is invoked by the CoordinatorEntity base class when new data is available.
        It updates the number entity's state and then calls the superclass's method, which
        schedules an update for Home Assistant to write the new state (`async_write_ha_state`).
        """
        self._update_number_state()
        super()._handle_coordinator_update()  # Schedules an update via async_write_ha_state.

    def _update_number_state(self) -> None:
        """
        Update the entity's internal state (`_attr_native_value` and `_attr_available`)
        from coordinator data.

        Retrieves the raw value for the node from the coordinator's data and parses it.
        """  # No return type for methods that update internal state.
        # Determine availability using HdgNodeEntity's `available` property.
        # This checks:
        # 1. Coordinator's overall status (last_update_success).
        # 2. Presence of this specific node's data in coordinator.data.
        self._attr_available = super().available

        if not self._attr_available:
            self._attr_native_value = None
            return

        raw_value_text = self.coordinator.data.get(self._node_id)
        self._attr_native_value = self._parse_value(raw_value_text)

    def _parse_value(self, raw_value_text: Optional[str]) -> Optional[Union[int, float]]:
        """
        Parse the raw string value from the API into an int or float.

        Assumes raw_value_text is a string (or None) as provided by the coordinator.
        Handles non-numeric characters/units (e.g., "21.5 °C").
        The return type (int or float) is determined by the 'setter_type'
        defined in SENSOR_DEFINITIONS, as this reflects how the value should
        be treated for setting, which often aligns with its display type.
        """
        if raw_value_text is None:
            return None
        cleaned_value = raw_value_text.strip()
        if not cleaned_value:
            return None

        # Determine the target type based on the 'setter_type' from the entity definition.
        setter_type = self._entity_definition.get("setter_type")

        # Use the appropriate parsing utility function based on the setter type.
        if setter_type == "int":
            return parse_int_from_string(cleaned_value, self._node_id, self.entity_id)

        # Default to float parsing for other setter types (e.g., 'float1', 'float2').
        # Note: parse_float_from_string handles extracting the numeric part and converting.
        parsed_float = parse_float_from_string(cleaned_value, self._node_id, self.entity_id)
        if parsed_float is None:
            _LOGGER.warning(
                f"Could not parse float for {self.entity_id} (node {self._node_id}) from raw value '{raw_value_text}' (cleaned: '{cleaned_value}')."
            )
            return None
        return parsed_float

    async def async_set_native_value(self, value: float) -> None:
        """
        Update the number entity's value, initiating a debounced API call.

        Home Assistant's NumberEntity base class provides `value` as a float.
        This method stores the latest requested `value` and schedules the
        `_process_debounced_value` method to be called after a debounce delay.
        If multiple calls to `async_set_native_value` occur within this delay,
        only the most recent value is processed. The actual API call queueing occurs
        in the `_process_debounced_value` method.
        """
        _LOGGER.debug(
            f"async_set_native_value called for {self.entity_id} with value {value}. "
            f"Storing value '{value}' and debouncing for {NUMBER_SET_VALUE_DEBOUNCE_DELAY_S}s."
        )

        # Store the latest value. This value will be picked up by _process_debounced_value.
        self._latest_value_to_queue = value

        # If an old timer exists, cancel it.
        if self._pending_api_call_timer:
            self._pending_api_call_timer()  # Call the cancel callback for the existing timer.
            _LOGGER.debug(f"Cancelled existing API call timer for {self.entity_id}.")
            self._pending_api_call_timer = None  # Explicitly set to None after cancelling.

        # Schedule the new job.
        # The name can still include 'value' for tracing the trigger, but the job itself won't use it.
        self._pending_api_call_timer = async_call_later(
            self.hass,
            NUMBER_SET_VALUE_DEBOUNCE_DELAY_S,
            HassJob(
                self._process_debounced_value,
                name=f"HdgBoilerNumber_DebounceProcess_{self.entity_id}_{value}",
            ),
        )

    async def _process_debounced_value(self, *args: Any) -> None:
        """
        Process the latest debounced value and queue it for the API call.

        This method is called by the `HassJob` scheduled in `async_set_native_value`
        after the debounce period. It retrieves the latest value stored in
        `self._latest_value_to_queue`, formats it, and delegates the actual
        queueing to the HdgDataUpdateCoordinator.

        Args:
            *args: Positional arguments passed by `async_call_later` (typically
                   the datetime of execution), which are ignored by this method.
        """
        # The job associated with this timer has started execution.
        # We will clear _pending_api_call_timer in a finally block to ensure it's
        # reset regardless of execution outcome.
        try:
            # Retrieve the latest value that was stored by async_set_native_value.
            value_to_process = self._latest_value_to_queue

            # Reset the stored value *immediately*. This ensures that if async_set_native_value
            # is called again *while this method is running*, the new value will be stored
            # and processed by a *new* timer, preventing this timer from re-processing it.
            self._latest_value_to_queue = None

            if value_to_process is None:
                _LOGGER.debug(
                    f"_process_debounced_value for {self.entity_id}: No value was pending. Exiting."
                )
                return

            # Get the setter type from the entity definition. This should be present and valid
            # because _create_number_entity_if_valid checks for it.
            setter_type = cast(str, self._entity_definition.get("setter_type"))

            try:
                # Format the numeric value into the string expected by the HDG API.
                # This uses the shared utility function.
                api_value_to_send_str = format_value_for_api(float(value_to_process), setter_type)

                # Delegate the actual set operation to the coordinator.
                success = await self.coordinator.async_set_node_value_if_changed(
                    node_id=self._node_id,  # Base node ID for the API call.
                    new_value_str_for_api=api_value_to_send_str,  # Pass the formatted string.
                    entity_name_for_log=self.name
                    or self.entity_id,  # Use HA name or entity_id for logging.
                )
                if not success:
                    _LOGGER.error(
                        f"Failed to queue/set value for {self.name or self.entity_id} (coordinator reported unchanged or queue full) for value {value_to_process}."
                    )
                else:
                    _LOGGER.info(
                        f"Successfully queued set request for {self.name or self.entity_id} to {value_to_process} (API value: {api_value_to_send_str})."
                    )

            # Catch specific errors that format_value_for_api or the coordinator might raise.
            except ValueError as err:  # Catches ValueError from format_value_for_api
                _LOGGER.error(
                    f"Configuration error for {self.entity_id} preventing value set. "
                    f"Details: {err}. Please check SENSOR_DEFINITIONS."
                )
            except (
                HdgApiError
            ) as err:  # Catches HdgApiError from coordinator.async_set_node_value_if_changed
                _LOGGER.error(
                    f"API error during coordinator.async_set_node_value_if_changed for {self.entity_id} with value {value_to_process}: {err}"
                )
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.exception(
                    f"Unexpected error during processing/queueing of debounced value for {self.entity_id} with value {value_to_process}: {err}"
                )
        finally:
            # This timer instance has now executed its job (successfully or not, or exited early).
            # Clear the reference, indicating no *active* timer is pending from this scheduling.
            self._pending_api_call_timer = None
            _LOGGER.debug(
                f"Cleared _pending_api_call_timer for {self.entity_id} after execution of its job."
            )


def _determine_ha_number_step_val(
    entity_def: SensorDefinition,
    translation_key: str,  # For logging
    raw_hdg_node_id: str,  # For logging
) -> Optional[float]:
    """
    Determine the native_step for the HA NumberEntity based on SENSOR_DEFINITIONS.

    Returns the step value as a float. If a critical configuration error is found
    (e.g., invalid or negative step value in definitions), it logs an error and
    returns None, signaling the caller to skip the creation of this entity.
    """
    # Get the setter type to potentially infer a default step if 'setter_step' is missing.
    setter_type_for_step_default = entity_def.get("setter_type", "").strip().lower()
    raw_step_val_config = entity_def.get("setter_step")
    step_val: float  # Will hold the determined step value.

    if raw_step_val_config is None:
        # If 'setter_step' is not explicitly defined, infer a default step based on 'setter_type'.
        # Floats typically use 0.1, integers use 1.0.
        step_val = 0.1 if setter_type_for_step_default in {"float1", "float2"} else 1.0
        _LOGGER.debug(
            f"'setter_step' not defined for translation_key '{translation_key}' (Node {raw_hdg_node_id}). "
            f"Detected setter_type '{setter_type_for_step_default}', defaulting HA NumberEntity step to {step_val}."
        )
        return step_val

    try:
        # Attempt to parse the configured 'setter_step' as a float.
        parsed_step_val_config = float(raw_step_val_config)
    except (ValueError, TypeError):
        _LOGGER.error(
            f"Invalid 'setter_step' value '{raw_step_val_config}' in SENSOR_DEFINITIONS for translation_key '{translation_key}' (Node {raw_hdg_node_id}). "
            f"Must be a number. This entity will be skipped."
        )
        return None  # Indicate error: entity should not be created.

    if parsed_step_val_config < 0.0:
        _LOGGER.error(
            f"Invalid 'setter_step' value {parsed_step_val_config} (negative) in SENSOR_DEFINITIONS for translation_key '{translation_key}' (Node {raw_hdg_node_id}). "
            f"Step must be non-negative. This entity will be skipped."
        )
        return None  # Indicate error: entity should not be created.
    elif parsed_step_val_config == 0.0:
        # A 'setter_step' of 0.0 in SENSOR_DEFINITIONS implies that only the min_value is settable.
        # However, Home Assistant's NumberEntity UI requires a positive step for the slider/box.
        # We use a default positive step for the UI representation, and the service call validation
        # (`async_handle_set_node_value`) will enforce the 0.0 step logic (only min_val allowed).
        step_val = 0.1 if setter_type_for_step_default in {"float1", "float2"} else 1.0
        _LOGGER.warning(
            f"SENSOR_DEFINITIONS for '{translation_key}' (Node {raw_hdg_node_id}) has a setter_step of 0.0. "
            f"Using HA NumberEntity step {step_val} for UI. "
            "Service calls will correctly enforce the 0.0 step logic (meaning only min_val is allowed if defined)."
        )
        return step_val

    # If 'setter_step' is positive and valid.
    return parsed_step_val_config


def _create_number_entity_if_valid(
    translation_key: str,
    entity_def: SensorDefinition,
    coordinator: HdgDataUpdateCoordinator,
    api_client: HdgApiClient,
) -> Optional[HdgBoilerNumber]:
    """
    Validate entity definition and create HdgBoilerNumber entity if valid.

    Ensures that essential keys ('hdg_node_id', 'setter_type', 'setter_min_val',
    'setter_max_val') are present and valid in the SENSOR_DEFINITIONS entry.
    It also determines the appropriate step value for the Home Assistant NumberEntity.

    Returns:
        The HdgBoilerNumber entity if the definition is valid, otherwise None.
    """
    # 1. Validate presence and type of 'hdg_node_id'.
    hdg_node_id_with_suffix = entity_def.get("hdg_node_id")
    if not isinstance(hdg_node_id_with_suffix, str) or not hdg_node_id_with_suffix:
        _LOGGER.warning(
            f"Skipping number entity for translation_key '{translation_key}': "
            f"missing or invalid 'hdg_node_id' in SENSOR_DEFINITIONS (value: {hdg_node_id_with_suffix})."
        )
        return None

    raw_hdg_node_id = strip_hdg_node_suffix(hdg_node_id_with_suffix)

    # 2. Validate presence and type of 'setter_type'.
    setter_type = entity_def.get("setter_type")
    if not isinstance(setter_type, str) or not setter_type:
        _LOGGER.warning(
            f"Skipping number entity for translation_key '{translation_key}' (HDG Node {raw_hdg_node_id}): "
            f"Missing or invalid 'setter_type' in SENSOR_DEFINITIONS (value: {setter_type})."
        )
        return None

    # 3. Validate presence and type of 'setter_min_val' and 'setter_max_val'.
    min_val_def = entity_def.get("setter_min_val")
    max_val_def = entity_def.get("setter_max_val")

    try:
        # Attempt to convert min and max values to floats.
        min_val = float(min_val_def)
        max_val = float(max_val_def)
    except (ValueError, TypeError) as e:
        _LOGGER.error(
            f"Invalid 'setter_min_val' ('{min_val_def}') or 'setter_max_val' ('{max_val_def}') "
            f"in SENSOR_DEFINITIONS for '{translation_key}' (Node {raw_hdg_node_id}): {e}. "
            "Values must be numbers. This entity will be skipped."
        )
        return None

    # 4. Determine and validate the step value for the HA NumberEntity.
    ha_native_step_val = _determine_ha_number_step_val(entity_def, translation_key, raw_hdg_node_id)
    if (
        ha_native_step_val is None
    ):  # Indicates a critical error in step definition logged by _determine_ha_number_step_val.
        return None  # Entity creation will be skipped.

    # 5. All essential parameters seem valid. Create the NumberEntityDescription.
    description = NumberEntityDescription(
        key=translation_key,  # Used for internal HA identification.
        name=None,  # Name will be derived from translation_key by HA.
        translation_key=translation_key,  # Enables localized entity names.
        icon=entity_def.get("icon"),
        device_class=entity_def.get("ha_device_class"),
        native_unit_of_measurement=entity_def.get("ha_native_unit_of_measurement"),
        entity_category=entity_def.get("entity_category"),
        native_min_value=min_val,
        native_max_value=max_val,
        native_step=ha_native_step_val,
        mode=NumberMode.BOX,  # Use BOX mode for direct input.
    )
    _LOGGER.debug(
        f"Preparing HDG number entity for translation_key: {translation_key} "
        f"(HDG Node for API set: {raw_hdg_node_id}, SENSOR_DEF Node ID: {hdg_node_id_with_suffix})"
    )
    # Create and return the HdgBoilerNumber entity instance.
    return HdgBoilerNumber(coordinator, api_client, description, entity_def)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Set up HDG Bavaria Boiler number entities from a config entry.

    Iterates through SENSOR_DEFINITIONS, creating number entities for entries
    where 'ha_platform' is "number" and all required setter parameters
    ('setter_type', 'setter_min_val', 'setter_max_val', 'setter_step') are validly defined.
    """
    # Retrieve the coordinator and API client instances from hass.data.
    integration_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HdgDataUpdateCoordinator = integration_data["coordinator"]
    api_client: HdgApiClient = integration_data["api_client"]

    number_entities: list[HdgBoilerNumber] = []

    # Iterate through all defined entities in SENSOR_DEFINITIONS.
    for translation_key, entity_definition_dict in SENSOR_DEFINITIONS.items():
        entity_def = cast(SensorDefinition, entity_definition_dict)

        # Check if the entity definition is for the 'number' platform.
        if entity_def.get("ha_platform") == "number":
            # Validate the definition and create the entity if it's valid.
            if entity := _create_number_entity_if_valid(
                translation_key, entity_def, coordinator, api_client
            ):
                number_entities.append(entity)

    # Add the created entities to Home Assistant.
    if number_entities:
        async_add_entities(number_entities)
        _LOGGER.info(f"Added {len(number_entities)} HDG Bavaria number entities.")
    else:
        _LOGGER.info(
            "No number entities to add. This may be due to missing or invalid "
            "setter parameters in SENSOR_DEFINITIONS for 'number' platform entities."
        )
