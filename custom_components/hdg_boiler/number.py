"""
Platform for number entities for the HDG Bavaria Boiler integration.

Creates and manages 'number' entities, allowing users to modify numeric settings
on their HDG Bavaria boiler. These entities handle state updates from the
data coordinator and implement debouncing for API calls when setting new values
to prevent overwhelming the boiler's API.
"""

__version__ = "0.8.26"

import logging
from typing import Any, Optional, cast, Union
import asyncio
import functools

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
)

_LOGGER = logging.getLogger(DOMAIN)


class HdgInvalidSetterTypeError(ValueError):
    """Raised when an invalid setter_type is encountered during formatting for an API call."""

    pass


class HdgBoilerNumber(HdgNodeEntity, NumberEntity):
    """
    Represents an HDG Bavaria Boiler number entity.

    This entity allows users to view and modify numeric settings on the boiler.
    It receives state updates from the central HdgDataUpdateCoordinator.
    When a user sets a new value, the entity debounces the API call to avoid
    sending too many requests in rapid succession. The actual API call to
    set the value is delegated to the coordinator.
    """

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        api_client: HdgApiClient,
        entity_description: NumberEntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """
        Initialize the HDG Boiler number entity.

        Args:
            coordinator: The data update coordinator.
            api_client: The API client for direct communication (though setting is via coordinator).
            entity_description: Standard Home Assistant entity description.
            entity_definition: Custom entity definition from SENSOR_DEFINITIONS.
        """
        hdg_api_node_id_from_def = entity_definition["hdg_node_id"]
        super().__init__(
            coordinator, strip_hdg_node_suffix(hdg_api_node_id_from_def), entity_definition
        )

        self.entity_description = entity_description
        self._api_client = api_client  # Retained, though set operations go via coordinator.
        self._pending_api_call_timer: Optional[asyncio.TimerHandle] = None
        # self._pending_value_to_set is no longer needed as the value is
        # captured by functools.partial for the HassJob.
        self._attr_native_value = None  # Stores the current numeric value of the entity.
        self._update_number_state()  # Initial state update.

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

        setter_type = self._entity_definition.get("setter_type")
        if setter_type == "int":
            return parse_int_from_string(cleaned_value, self._node_id, self.entity_id)

        # Default to float if not 'int' (covers 'float1', 'float2', or other future float types)
        parsed_float = parse_float_from_string(cleaned_value, self._node_id, self.entity_id)
        if parsed_float is None:
            _LOGGER.warning(f"Could not parse float for {self.entity_id} from '{cleaned_value}'")
            return None
        return parsed_float

    async def async_set_native_value(self, value: float) -> None:
        """
        Update the number entity's value, initiating a debounced API call.

        Home Assistant's NumberEntity base class provides `value` as a float.
        This method schedules the `_execute_set_value_api_call` after a debounce
        delay. If multiple calls to `async_set_native_value` occur within the
        delay, previous pending calls are cancelled, and only the latest one
        is executed.
        """
        _LOGGER.debug(
            f"async_set_native_value called for {self.entity_id} with value {value}. "
            f"Debouncing for {NUMBER_SET_VALUE_DEBOUNCE_DELAY_S}s."
        )

        if self._pending_api_call_timer:
            self._pending_api_call_timer()  # Call the cancel callback for the existing timer.
            _LOGGER.debug(f"Cancelled existing API call timer for {self.entity_id}.")
            self._pending_api_call_timer = None  # Explicitly set to None after cancelling.

        # Create a partial function that binds the current 'value'
        # to the _execute_set_value_api_call method.
        # This ensures that the value at the time of scheduling is used for this specific call.
        action_with_value = functools.partial(self._execute_set_value_api_call, value_to_send=value)

        self._pending_api_call_timer = async_call_later(
            self.hass,
            NUMBER_SET_VALUE_DEBOUNCE_DELAY_S,
            HassJob(
                action_with_value,
                name=f"HdgBoilerNumber_SetValue_{self.entity_id}_{value}",  # Include value for easier log tracing
            ),
        )

    def _format_value_for_api(
        self, numeric_value_to_format: float, node_setter_type: Optional[str]
    ) -> str:
        """
        Format the numeric value into the string representation expected by the HDG API.

        This depends on the 'setter_type' (e.g., "int", "float1", "float2")
        defined in SENSOR_DEFINITIONS for the specific node.
        """
        if node_setter_type == "int":
            return str(int(round(numeric_value_to_format)))
        elif node_setter_type == "float1":
            # Format to one decimal place, ensuring '.' is used as decimal separator.
            return f"{numeric_value_to_format:.1f}".replace(",", ".")
        elif node_setter_type == "float2":
            # Format to two decimal places, ensuring '.' is used as decimal separator.
            return f"{numeric_value_to_format:.2f}".replace(",", ".")
        else:
            # This case indicates a misconfiguration in SENSOR_DEFINITIONS.
            msg = (
                f"Misconfiguration in SENSOR_DEFINITIONS for {self.entity_id}: "
                f"Unknown 'setter_type' ('{node_setter_type}') encountered in _format_value_for_api. "
                "Cannot format value for API. Please check entity definition."
            )
            _LOGGER.error(msg)
            # Raising an error as this is an unrecoverable situation for this call.
            raise HdgInvalidSetterTypeError(msg)

    async def _execute_set_value_api_call(self, *args: Any, value_to_send: float) -> None:
        """
        Execute the API call to set the node value after the debounce period.

        This method is called by the `HassJob` scheduled in `async_set_native_value`.
        It formats the value based on 'setter_type' from SENSOR_DEFINITIONS and
        then delegates the actual API call to the HdgDataUpdateCoordinator.

        Args:
            *args: Positional arguments passed by async_call_later (e.g., datetime of execution), ignored.
            value_to_send: The specific value that was pending when this particular timer was scheduled.
        The `value_to_send` is the specific value that was pending when this
        particular timer was scheduled.
        """
        # The job associated with this timer has started execution.
        # We will clear _pending_api_call_timer in a finally block to ensure it's
        # reset regardless of execution outcome.
        try:
            try:
                # value_to_send is already a float from async_set_native_value
                value_to_send_numeric = value_to_send
            except (
                ValueError,
                TypeError,
            ) as e:  # Should not happen if value_to_send is always float
                _LOGGER.error(
                    f"Invalid scheduled value '{value_to_send}' (type: {type(value_to_send)}) "
                    f"cannot be set for {self.entity_id}. Error: {e}. Aborting API call."
                )
                return  # Exit early if initial value processing fails.

            _LOGGER.info(
                f"Executing debounced API call for {self.entity_id} (Node ID: {self._node_id}) with scheduled value {value_to_send_numeric}"
            )

            try:
                api_value_to_send_str = self._format_value_for_api(
                    value_to_send_numeric, self._entity_definition.get("setter_type")
                )
                success = await self.coordinator.async_set_node_value_if_changed(
                    node_id=self._node_id,  # Base node ID for the API call.
                    new_value_to_set=api_value_to_send_str,  # Formatted string value for the API.
                    entity_name_for_log=self.name
                    or self.entity_id,  # Use HA name or entity_id for logging.
                )
                if not success:
                    _LOGGER.error(
                        f"Failed to set value for {self.name or self.entity_id} (API call reported failure by coordinator) for value {value_to_send_numeric}."
                    )
                else:
                    _LOGGER.info(
                        f"Successfully set {self.name or self.entity_id} to {value_to_send_numeric} (API value: {api_value_to_send_str})."
                    )

            except HdgInvalidSetterTypeError as err:  # Catch specific configuration error first
                _LOGGER.error(
                    f"Configuration error for {self.entity_id} preventing value set. "
                    f"Details: {err}. Please check SENSOR_DEFINITIONS."
                )
            # HdgApiError is more specific than ValueError for API communication issues.
            except HdgApiError as err:
                _LOGGER.error(
                    f"API error setting value for {self.entity_id} to {value_to_send_numeric}: {err}"
                )
            except (
                ValueError
            ) as err:  # Catch other potential ValueErrors during formatting (less likely now)
                _LOGGER.error(
                    f"Formatting error for value {value_to_send_numeric} for {self.entity_id}: {err}"
                )
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.exception(
                    f"Unexpected error during API call execution for {self.entity_id} with value {value_to_send_numeric}: {err}"
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

    Returns the step value. If a critical configuration error is found (e.g.,
    invalid step value in definitions), it logs an error and returns None,
    prompting the caller (e.g., `_create_number_entity_if_valid`) to skip
    the creation of this entity.
    """
    setter_type_for_step_default = entity_def.get("setter_type", "").strip().lower()
    raw_step_val_config = entity_def.get("setter_step")
    step_val: float  # Will hold the determined step value.

    if raw_step_val_config is None:
        # If 'setter_step' is not defined, infer a default step based on 'setter_type'.
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
        # However, Home Assistant's NumberEntity UI requires a positive step.
        # We use a default positive step for the UI, and the service call validation
        # (`async_handle_set_node_value`) will enforce the 0.0 step logic.
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

    Checks for essential keys in SENSOR_DEFINITIONS ('hdg_node_id', 'setter_type',
    'setter_min_val', 'setter_max_val') and validates their types.
    Determines the step value for the Home Assistant NumberEntity.

    Returns:
        The HdgBoilerNumber entity if the definition is valid, otherwise None.
    """
    hdg_node_id_with_suffix = entity_def.get("hdg_node_id")
    if not hdg_node_id_with_suffix:
        _LOGGER.warning(
            f"Skipping number entity for translation_key '{translation_key}': "
            f"missing 'hdg_node_id' in SENSOR_DEFINITIONS."
        )
        return None

    raw_hdg_node_id = strip_hdg_node_suffix(hdg_node_id_with_suffix)

    if not entity_def.get("setter_type"):
        _LOGGER.warning(
            f"Skipping number entity for translation_key '{translation_key}' (HDG Node {raw_hdg_node_id}): "
            f"Missing 'setter_type' in SENSOR_DEFINITIONS."
        )
        return None

    # Validate presence of min and max values, essential for NumberEntity.
    if "setter_min_val" not in entity_def or "setter_max_val" not in entity_def:
        _LOGGER.warning(
            f"Skipping number entity for translation_key '{translation_key}' (HDG Node {raw_hdg_node_id}): "
            f"Missing 'setter_min_val' or 'setter_max_val' in SENSOR_DEFINITIONS."
        )
        return None

    # Determine and validate the step value for the HA NumberEntity.
    ha_native_step_val = _determine_ha_number_step_val(entity_def, translation_key, raw_hdg_node_id)
    if ha_native_step_val is None:  # Indicates a critical error in step definition.
        return None  # Entity creation will be skipped.

    try:
        # Ensure min and max values are valid floats.
        min_val = float(entity_def["setter_min_val"])
        max_val = float(entity_def["setter_max_val"])
    except (ValueError, TypeError) as e:
        _LOGGER.error(
            f"Invalid 'setter_min_val' or 'setter_max_val' in SENSOR_DEFINITIONS for '{translation_key}' (Node {raw_hdg_node_id}): {e}. "
            "Values must be numbers. This entity will be skipped."
        )
        return None

    # Create the NumberEntityDescription for Home Assistant.
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
    return HdgBoilerNumber(coordinator, api_client, description, entity_def)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Set up HDG Bavaria Boiler number entities from a config entry.

    Iterates through SENSOR_DEFINITIONS, creating number entities for those configured
    with 'ha_platform: "number"' and having all necessary setter parameters
    ('setter_type', 'setter_min_val', 'setter_max_val').
    """
    integration_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HdgDataUpdateCoordinator = integration_data["coordinator"]
    api_client: HdgApiClient = integration_data["api_client"]

    number_entities: list[HdgBoilerNumber] = []

    for translation_key, entity_definition_dict in SENSOR_DEFINITIONS.items():
        entity_def = cast(SensorDefinition, entity_definition_dict)

        if entity_def.get("ha_platform") == "number":  # Only process 'number' platform entities.
            # Validate and create the entity if the definition is complete and valid.
            if entity := _create_number_entity_if_valid(
                translation_key, entity_def, coordinator, api_client
            ):
                number_entities.append(entity)

    if number_entities:
        async_add_entities(number_entities)
        _LOGGER.info(f"Added {len(number_entities)} HDG Bavaria number entities.")
    else:
        _LOGGER.info(
            "No number entities to add. This may be due to missing or invalid "
            "setter parameters in SENSOR_DEFINITIONS for 'number' platform entities."
        )
