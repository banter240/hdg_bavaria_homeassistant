"""
Service handlers for the HDG Bavaria Boiler integration.

This module defines the logic for custom Home Assistant services provided by
the HDG Bavaria Boiler integration, specifically for setting and getting HDG node values.
"""

__version__ = "0.8.4"

from decimal import Decimal, InvalidOperation
import logging
from typing import Any, Dict, Union, cast, Optional

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .api import HdgApiError
from .coordinator import HdgDataUpdateCoordinator
from .const import (
    ATTR_NODE_ID,
    ATTR_VALUE,
    DOMAIN,
    SERVICE_SET_NODE_VALUE,
    SERVICE_GET_NODE_VALUE,
)
from .definitions import (
    SensorDefinition,
    SENSOR_DEFINITIONS,
)
from .utils import (
    extract_base_node_id,
    safe_float_convert,
    format_value_for_api,
)

_LOGGER = logging.getLogger(DOMAIN)


# Index SensorDefinitions by base node id for fast lookup.
def _build_sensor_definitions_by_base_node_id() -> Dict[str, list[SensorDefinition]]:
    """
    Build an index of sensor definitions keyed by their base HDG node ID.

    This allows quick lookup of all definitions associated with a specific base node ID.
    """
    index: dict[str, list[SensorDefinition]] = {}

    for definition_dict in SENSOR_DEFINITIONS.values():
        definition = cast(SensorDefinition, definition_dict)
        # Ensure hdg_node_id exists and is a string before processing
        hdg_node_id_val = definition.get("hdg_node_id")
        if isinstance(hdg_node_id_val, str) and (
            base_hdg_node_id_from_def := extract_base_node_id(hdg_node_id_val)
        ):
            if base_hdg_node_id_from_def:  # Ensure base_id is not empty
                if base_hdg_node_id_from_def not in index:
                    index[base_hdg_node_id_from_def] = []
                index[base_hdg_node_id_from_def].append(definition)
        else:
            _LOGGER.warning(
                f"Skipping definition in _build_sensor_definitions_by_base_node_id due to missing or invalid 'hdg_node_id': {definition_dict.get('translation_key', 'Unknown Key')}"
            )
    return index


SENSOR_DEFINITIONS_BY_BASE_NODE_ID = _build_sensor_definitions_by_base_node_id()


def _validate_service_call_input(call: ServiceCall) -> tuple[str, Any]:
    """
    Validate and extract node_id and value from the service call.

    Ensures that the required `node_id` and `value` attributes are present
    in the service call data.
    Raises ServiceValidationError if required fields are missing.
    """
    node_id_input = call.data.get(ATTR_NODE_ID)
    value_to_set = call.data.get(ATTR_VALUE)

    if node_id_input is None or value_to_set is None:
        _LOGGER.error(
            f"Service '{SERVICE_SET_NODE_VALUE}' missing '{ATTR_NODE_ID}' or '{ATTR_VALUE}'."
        )
        raise ServiceValidationError(
            f"'{ATTR_NODE_ID}' and '{ATTR_VALUE}' required for {SERVICE_SET_NODE_VALUE}."
        )
    return str(node_id_input).strip(), value_to_set


def _find_settable_sensor_definition(node_id_str: str) -> SensorDefinition:
    """
    Find and return the SensorDefinition for a settable 'number' node.

    Queries the cached `SENSOR_DEFINITIONS_BY_BASE_NODE_ID` index to find definitions
    matching the base node ID. It then filters for definitions where `ha_platform`
    is "number" and `setter_type` is defined, returning the single matching definition.

    Raises:
    Args:
        node_id_str: The base HDG node ID to search for.
    """
    definitions_for_base = SENSOR_DEFINITIONS_BY_BASE_NODE_ID.get(node_id_str, [])
    settable_definitions = [
        d for d in definitions_for_base if d.get("ha_platform") == "number" and d.get("setter_type")
    ]

    if not settable_definitions:
        error_detail = "No SENSOR_DEFINITIONS entry found or not a settable 'number' platform with a 'setter_type'."
        if definitions_for_base:
            error_detail = (
                f"Node ID found, but no valid settable 'number' definition. "
                f"Found {len(definitions_for_base)} definition(s), but none matched criteria "
                f"(ha_platform='number' and 'setter_type' defined)."
            )
        _LOGGER.error(
            f"Node ID '{node_id_str}' not configured as settable 'number'. Details: {error_detail}"
        )
        raise ServiceValidationError(
            f"Node ID '{node_id_str}' not settable. Reason: {error_detail}"
        )

    if len(settable_definitions) > 1:
        _LOGGER.error(
            f"Multiple settable 'number' SensorDefinitions found for node_id '{node_id_str}': "
            f"{[repr(d) for d in settable_definitions]}. "
            "Please ensure only one settable definition exists per node to avoid ambiguity."
        )
        raise ServiceValidationError(
            f"Multiple settable 'number' definitions for node ID '{node_id_str}'. Conflicting definitions: {[repr(d) for d in settable_definitions]}"
        )
    return settable_definitions[0]


def _coerce_value_to_numeric_type(
    value_to_set: Any, node_type: Optional[str], entity_name_for_log: str
) -> Union[int, float]:
    """
    Coerce input value to the target numeric type (int or float) based on setter_type.

    Args:
        value_to_set: The raw value provided in the service call.
        node_type: The expected 'setter_type' from SENSOR_DEFINITIONS ("int", "float1", "float2").
        entity_name_for_log: The name of the entity for logging context.

    Returns:
        The value coerced to an int or float.

    Raises:
        ServiceValidationError: If the value cannot be coerced to the expected type.
    """
    try:
        if node_type == "int":
            # Attempt float conversion first to handle "10.0" correctly, then int.
            temp_float = float(value_to_set)
            if temp_float != int(temp_float):
                raise ValueError("Value is not a whole number for int type.")
            return int(temp_float)
        elif node_type in ["float1", "float2"]:
            # For float types, simply coerce to float. Rounding for API is handled later.
            return float(value_to_set)
        else:
            # This case should ideally be caught by _find_settable_sensor_definition,
            # but included as a safeguard.
            raise ValueError(f"Unknown or missing setter_type '{node_type}'.")
    except (ValueError, TypeError) as exc:
        error_message = f"Value '{value_to_set}' not convertible to expected numeric type for '{node_type}': {exc}"
        _LOGGER.error(
            f"Type coercion failed for node '{entity_name_for_log}': {error_message}",
            exc_info=True,
        )
        raise ServiceValidationError(
            f"Type validation failed for node '{entity_name_for_log}' with value '{value_to_set}'. Reason: {error_message}"
        ) from exc


def _perform_decimal_step_validation(
    val_decimal: Decimal,
    min_val_decimal: Decimal,
    step_decimal: Decimal,
    entity_name_for_log: str,
    node_id_str_for_log: str,
    original_value_to_set_for_log: Any,
    node_step_def_for_log: Any,
) -> None:
    """
    Perform step validation using Decimal objects for precision.

    Args:
        val_decimal: The value to validate, as a Decimal.
        min_val_decimal: The minimum allowed value, as a Decimal.
        step_decimal: The step value, as a Decimal.
        entity_name_for_log: Entity name for logging.
        node_id_str_for_log: Node ID for logging.
        original_value_to_set_for_log: Original value for logging.
        node_step_def_for_log: Step definition for logging.

    Raises:
        ServiceValidationError: If the value does not align with the step from the minimum.
    """
    if step_decimal < Decimal(0):
        _LOGGER.error(
            f"Config error: setter_step '{node_step_def_for_log}' in SENSOR_DEFINITIONS must be non-negative for node '{entity_name_for_log}'."
        )
        raise ServiceValidationError(
            f"Configuration error for node '{entity_name_for_log}': Step must be non-negative."
        )
    elif step_decimal == Decimal(0):
        if val_decimal != min_val_decimal:
            raise ServiceValidationError(
                f"Value {val_decimal} not allowed for node '{entity_name_for_log}'. With step 0, only min_value {min_val_decimal} is valid."
            )
    else:  # Positive step
        # Using a small epsilon for floating point comparisons with Decimal.
        decimal_epsilon = Decimal("1e-9")
        remainder = (val_decimal - min_val_decimal) % step_decimal

        # Check if remainder is very close to 0 or very close to step_decimal (for floating point inaccuracies)
        is_close_to_zero = abs(remainder) < decimal_epsilon
        is_close_to_step = abs(remainder - step_decimal) < decimal_epsilon

        if not (is_close_to_zero or is_close_to_step):
            raise ServiceValidationError(
                f"Value {val_decimal} for node '{entity_name_for_log}' (ID: {node_id_str_for_log}) "
                f"is not a valid step from {min_val_decimal} with step {step_decimal}. "
                f"Original value: '{original_value_to_set_for_log}'. Remainder: {remainder}, Epsilon: +/-{decimal_epsilon}"
            )
    _LOGGER.debug(
        f"Decimal step validation passed for node '{entity_name_for_log}' (ID: {node_id_str_for_log}), value: {val_decimal}"
    )


def _validate_value_range_and_step(
    coerced_numeric_value: Union[int, float],  # Type-coerced value
    min_val_def: Any,  # Raw definition value for min
    max_val_def: Any,  # Raw definition value for max
    node_step_def: Any,  # Raw definition value for step
    entity_name_for_log: str,
    node_id_str_for_log: str,
    original_value_to_set_for_log: Any,
) -> None:
    """
    Validate the numeric value against configured min, max, and step.

    Args:
        coerced_numeric_value: The numeric value after type coercion.
        min_val_def: The 'setter_min_val' from SENSOR_DEFINITIONS.
        max_val_def: The 'setter_max_val' from SENSOR_DEFINITIONS.
        node_step_def: The 'setter_step' from SENSOR_DEFINITIONS.
        entity_name_for_log: Entity name for logging.
        node_id_str_for_log: Node ID for logging.
        original_value_to_set_for_log: Original value for logging.

    Raises:
        ServiceValidationError: If the value is outside the range or does not match the step.
    """
    is_valid_for_range = True
    error_message = ""
    numeric_value_for_check = float(coerced_numeric_value)

    # Validate against 'setter_min_val'.
    if min_val_def is not None:
        conversion_ok, min_val_float, conv_error_msg = safe_float_convert(
            min_val_def, "setter_min_val", entity_name_for_log
        )
        if not conversion_ok or min_val_float is None:
            is_valid_for_range = False
            error_message = conv_error_msg
        elif numeric_value_for_check < min_val_float:
            is_valid_for_range = False
            error_message = f"Value {numeric_value_for_check} < min {min_val_float}."

    # Validate against 'setter_max_val'.
    if is_valid_for_range and max_val_def is not None:
        conversion_ok, max_val_float, conv_error_msg = safe_float_convert(
            max_val_def, "setter_max_val", entity_name_for_log
        )
        if not conversion_ok:
            is_valid_for_range = False
            error_message = conv_error_msg
        elif max_val_float is not None and numeric_value_for_check > max_val_float:
            is_valid_for_range = False
            error_message = f"Value {numeric_value_for_check} > max {max_val_float}."

    if not is_valid_for_range:
        raise ServiceValidationError(
            f"Range validation failed for node '{entity_name_for_log}' (ID: {node_id_str_for_log}) with value '{original_value_to_set_for_log}'. Reason: {error_message}"
        )

    # Step validation using Decimal for precision, only if range validation passed.
    if node_step_def is not None and min_val_def is not None:
        try:
            val_decimal = Decimal(str(coerced_numeric_value))
            min_val_decimal = Decimal(str(min_val_def))
            step_decimal = Decimal(str(node_step_def))

            _perform_decimal_step_validation(
                val_decimal,
                min_val_decimal,
                step_decimal,
                entity_name_for_log,
                node_id_str_for_log,
                original_value_to_set_for_log,
                node_step_def,
            )
        except InvalidOperation as dec_err:
            error_message = (
                f"Invalid numeric format for step validation (min, step, or value): {dec_err}"
            )
            _LOGGER.error(
                f"{error_message} for node '{entity_name_for_log}'. Input: value='{original_value_to_set_for_log}', min='{min_val_def}', step='{node_step_def}'."
            )
            raise ServiceValidationError(
                f"Step validation failed for node '{entity_name_for_log}' due to invalid number format. Reason: {error_message}"
            ) from dec_err


async def async_handle_set_node_value(
    hass: HomeAssistant,
    coordinator: HdgDataUpdateCoordinator,
    call: ServiceCall,
) -> None:
    """
    Handle the 'set_node_value' service call.

    This function validates the provided `node_id` against SENSOR_DEFINITIONS
    to ensure it's a settable 'number' entity. It then coerces the `value`
    to the expected numeric type, validates it against the node's configured
    range and step, formats it for the API, and finally delegates the set # sourcery skip: extract-method
    operation to the HdgDataUpdateCoordinator.
    """  # No return type for service handlers
    node_id_input = call.data.get(ATTR_NODE_ID)
    node_id_str, value_to_set_raw = _validate_service_call_input(call)
    _LOGGER.debug(
        f"Service '{SERVICE_SET_NODE_VALUE}': node_id='{node_id_input}' (base='{node_id_str}'), value='{value_to_set_raw}'"
    )

    sensor_def_for_node = _find_settable_sensor_definition(node_id_str)
    entity_name_for_log = sensor_def_for_node.get("translation_key", node_id_str)

    node_type = sensor_def_for_node.get("setter_type")
    min_val_def = sensor_def_for_node.get("setter_min_val")
    max_val_def = sensor_def_for_node.get("setter_max_val")
    node_step_def = sensor_def_for_node.get("setter_step")

    # 1. Coerce the input value to the expected numeric type (int or float).
    # This function raises ServiceValidationError on failure.
    coerced_numeric_value = _coerce_value_to_numeric_type(
        value_to_set_raw, node_type, entity_name_for_log
    )

    # 2. Validate the coerced numeric value against the defined range and step.
    # This function raises ServiceValidationError on failure.
    _validate_value_range_and_step(
        coerced_numeric_value=coerced_numeric_value,
        min_val_def=min_val_def,
        max_val_def=max_val_def,
        node_step_def=node_step_def,
        entity_name_for_log=entity_name_for_log,
        node_id_str_for_log=node_id_str,
        original_value_to_set_for_log=value_to_set_raw,
    )

    # 3. Format the validated numeric value into the string expected by the HDG API.
    # This uses the utility function from utils.py. It raises ValueError on configuration issues.
    try:
        # node_type is confirmed to be non-None and valid by _find_settable_sensor_definition
        api_value_to_send_str = format_value_for_api(coerced_numeric_value, cast(str, node_type))
    except ValueError as e:
        _LOGGER.error(
            f"Configuration error formatting value for API for node '{entity_name_for_log}' (ID: {node_id_str}): {e}"
        )
        raise ServiceValidationError(
            f"Configuration error formatting value for API for node '{entity_name_for_log}': {e}"
        ) from e

    # 4. Attempt to set the value via the coordinator.
    try:
        success = await coordinator.async_set_node_value_if_changed(
            node_id=node_id_str,  # Base node ID.
            new_value_str_for_api=api_value_to_send_str,  # Formatted string value for API.
            entity_name_for_log=entity_name_for_log,
        )
        if not success:
            _LOGGER.error(
                f"Failed to set node '{entity_name_for_log}' (ID: {node_id_str}). Coordinator reported failure (e.g., queue full or API error)."
            )
            # Raising HomeAssistantError to signal failure to the user in HA UI.
            raise HomeAssistantError(
                f"Failed to set node '{entity_name_for_log}' (ID: {node_id_str}). Coordinator reported failure."
            )
    except HdgApiError as err:
        _LOGGER.error(f"API error setting node '{entity_name_for_log}' (ID: {node_id_str}): {err}")
        raise HomeAssistantError(
            f"API error setting node '{entity_name_for_log}' (ID: {node_id_str}): {err}"
        ) from err
    except Exception as err:  # Catch any other unexpected errors
        _LOGGER.exception(
            f"Unexpected error setting node '{entity_name_for_log}' (ID: {node_id_str}): {err}"
        )
        raise HomeAssistantError(
            f"Unexpected error setting node '{entity_name_for_log}' (ID: {node_id_str}): {err}"
        ) from err


async def async_handle_get_node_value(
    hass: HomeAssistant, coordinator: HdgDataUpdateCoordinator, call: ServiceCall
) -> Dict[str, Any]:
    """# sourcery skip: extract-method
    Handle the 'get_node_value' service call.

    Retrieves the current raw string value for a specified node ID from the
    coordinator's internal data cache and returns it.
    Raises ServiceValidationError if the required `node_id` is missing.
    """
    node_id_input = call.data.get(ATTR_NODE_ID)

    if node_id_input is None:
        _LOGGER.error(f"Service '{SERVICE_GET_NODE_VALUE}' missing '{ATTR_NODE_ID}'.")
        raise ServiceValidationError(f"'{ATTR_NODE_ID}' required for {SERVICE_GET_NODE_VALUE}.")
    node_id_str = str(node_id_input).strip()
    _LOGGER.debug(
        f"Service '{SERVICE_GET_NODE_VALUE}': node_id='{node_id_input}' (base='{node_id_str}')"
    )

    if coordinator.data is None:
        _LOGGER.warning(
            f"Coordinator data not initialized. Cannot get value for node '{node_id_str}'."
        )
        return {
            "node_id": node_id_str,
            "value": None,
            "status": "coordinator_data_unavailable",
            "error": "Coordinator data store not initialized.",
        }

    if node_id_str in coordinator.data:
        value = coordinator.data[node_id_str]
        _LOGGER.debug(f"Node '{node_id_str}' found in coordinator. Raw value: '{value}'")
        return {"node_id": node_id_str, "value": value, "status": "found"}
    else:
        _LOGGER.warning(f"Node '{node_id_str}' not found in coordinator data.")
        _LOGGER.debug(
            f"Attempted find '{node_id_str}'. Available keys (sample): {list(coordinator.data.keys())[:20]}"
        )
        return {
            "node_id": node_id_str,
            "value": None,
            "status": "not_found",
            "error": f"Node ID '{node_id_str}' not found in coordinator's data.",
        }
