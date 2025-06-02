"""
Service handlers for the HDG Bavaria Boiler integration.

Defines logic for custom services like setting/getting HDG node values.
"""

__version__ = "0.7.6"

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
    coerce_and_round_float,
    extract_base_node_id,
    safe_float_convert,
)

_LOGGER = logging.getLogger(DOMAIN)


# Index SensorDefinitions by base node id for fast lookup.
def _build_sensor_definitions_by_base_node_id() -> Dict[str, list[SensorDefinition]]:
    """Build an index of sensor definitions keyed by their base HDG node ID."""
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
    """Validate and extract node_id and value from the service call."""
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
    """Find and return the SensorDefinition for a settable node."""
    sensor_def_for_node: SensorDefinition | None = None
    definitions_for_base = SENSOR_DEFINITIONS_BY_BASE_NODE_ID.get(node_id_str, [])

    for definition in definitions_for_base:
        if definition.get("ha_platform") == "number" and definition.get("setter_type"):
            sensor_def_for_node = definition
            break

    if not sensor_def_for_node:
        # Simplified error message generation for brevity in this helper
        error_detail = "No SENSOR_DEFINITIONS entry found or not a settable 'number'."
        if definitions_for_base:  # More specific if base ID was found but didn't qualify
            first_def = definitions_for_base[0]
            error_detail = (
                f"Node ID found, but not a valid settable 'number'. "
                f"First found def (hdg_node_id: {first_def.get('hdg_node_id')}): "
                f"platform='{first_def.get('ha_platform')}', setter_type='{first_def.get('setter_type')}'."
            )
        _LOGGER.error(
            f"Node ID '{node_id_str}' not configured as settable 'number'. Details: {error_detail}"
        )
        raise ServiceValidationError(
            f"Node ID '{node_id_str}' not settable. Reason: {error_detail}"
        )
    return sensor_def_for_node


def _coerce_and_validate_value_type(
    value_to_set: Any, node_type: Optional[str], entity_name_for_log: str
) -> Union[int, float, str]:
    """Coerce and validate the type of the value to be set."""
    validated_value: Union[int, float, str, None] = None
    is_valid = True
    error_message = ""

    try:
        if node_type == "int":
            temp_float = float(value_to_set)
            if temp_float != int(temp_float):
                is_valid = False
                error_message = f"Value '{value_to_set}' not whole number for int type."
            else:
                validated_value = int(temp_float)
        elif node_type == "float1":
            validated_value, is_valid, error_message = coerce_and_round_float(
                value_to_set, 1, "float1"
            )
        elif node_type == "float2":
            validated_value, is_valid, error_message = coerce_and_round_float(
                value_to_set, 2, "float2"
            )
        else:
            is_valid = False
            error_message = f"Node '{entity_name_for_log}' unknown setter_type '{node_type}'."
            _LOGGER.error(error_message)
    except (ValueError, TypeError) as exc:
        is_valid = False
        error_message = f"Value '{value_to_set}' not convertible to '{node_type}': {exc}"
        _LOGGER.error(error_message, exc_info=True)

    if not is_valid or validated_value is None:
        raise ServiceValidationError(
            f"Type validation failed for node '{entity_name_for_log}' with value '{value_to_set}'. Reason: {error_message}"
        )
    return validated_value


def _perform_decimal_step_validation(
    val_decimal: Decimal,
    min_val_decimal: Decimal,
    step_decimal: Decimal,
    entity_name_for_log: str,
    node_id_str_for_log: str,
    original_value_to_set_for_log: Any,
    node_step_def_for_log: Any,
) -> None:
    """Perform step validation using Decimal objects for precision."""
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
        decimal_epsilon = Decimal("1e-9")
        remainder = (val_decimal - min_val_decimal) % step_decimal
        is_close_to_zero = abs(remainder) < decimal_epsilon
        is_close_to_step = abs(remainder - step_decimal) < decimal_epsilon

        if not (is_close_to_zero or is_close_to_step):
            raise ServiceValidationError(
                f"Value {val_decimal} for node '{entity_name_for_log}' (ID: {node_id_str_for_log}) "
                f"is not a valid step from {min_val_decimal} with step {step_decimal}. "
                f"Original value: '{original_value_to_set_for_log}'. Rem: {remainder}, Epsilon: +/-{decimal_epsilon}"
            )
    _LOGGER.debug(
        f"Decimal step validation passed for node '{entity_name_for_log}' (ID: {node_id_str_for_log}), value: {val_decimal}"
    )


def _validate_value_range_and_step(
    validated_value: Union[int, float],  # Type-coerced value
    min_val_def: Any,
    max_val_def: Any,
    node_step_def: Any,
    entity_name_for_log: str,
    node_id_str_for_log: str,
    original_value_to_set_for_log: Any,
) -> None:
    """Validate the numeric value against configured min, max, and step."""
    is_valid = True
    error_message = ""
    numeric_value_for_check = float(validated_value)  # Ensure float for comparisons

    # Validate against 'setter_min_val'.
    if min_val_def is not None:
        conversion_ok, min_val_float, conv_error_msg = safe_float_convert(
            min_val_def, "setter_min_val", entity_name_for_log
        )
        if not conversion_ok or min_val_float is None:
            is_valid = False
            error_message = conv_error_msg
        elif numeric_value_for_check < min_val_float:
            is_valid = False
            error_message = f"Value {numeric_value_for_check} < min {min_val_float}."

    # Validate against 'setter_max_val'.
    if is_valid and max_val_def is not None:
        conversion_ok, max_val_float, conv_error_msg = safe_float_convert(
            max_val_def, "setter_max_val", entity_name_for_log
        )
        if not conversion_ok:
            is_valid = False
            error_message = conv_error_msg
        elif max_val_float is not None and numeric_value_for_check > max_val_float:
            is_valid = False
            error_message = f"Value {numeric_value_for_check} > max {max_val_float}."

    # Step validation using Decimal for precision.
    if is_valid and node_step_def is not None and min_val_def is not None:
        try:
            val_decimal = Decimal(str(validated_value))
            min_val_decimal = Decimal(str(min_val_def))
            step_decimal = Decimal(str(node_step_def))
        except InvalidOperation as dec_err:
            is_valid = False
            error_message = (
                f"Invalid numeric format for step validation (min, step, or value): {dec_err}"
            )
            _LOGGER.error(
                f"{error_message} for node '{entity_name_for_log}'. Input: value='{original_value_to_set_for_log}', min='{min_val_def}', step='{node_step_def}'."
            )
            # Ensure 'is_valid' is False if Decimal conversion fails, to prevent further processing.
            is_valid = False  # Explicitly set is_valid to False on critical conversion error

        if is_valid:  # Proceed if Decimal conversions were successful
            # Delegate step validation to the new helper function.
            # It will raise ServiceValidationError if step validation fails.
            _perform_decimal_step_validation(
                val_decimal,
                min_val_decimal,
                step_decimal,
                entity_name_for_log,
                node_id_str_for_log,
                original_value_to_set_for_log,
                node_step_def,
            )
    elif (
        not is_valid
    ):  # This 'elif' handles cases where 'is_valid' became False before Decimal step check (e.g. range fail or Decimal conversion fail)
        raise ServiceValidationError(
            f"Range/step validation failed for node '{entity_name_for_log}' (ID: {node_id_str_for_log}) with value '{original_value_to_set_for_log}'. Reason: {error_message}"
        )


async def async_handle_set_node_value(
    hass: HomeAssistant,
    coordinator: HdgDataUpdateCoordinator,
    call: ServiceCall,
) -> None:
    """
    Handle the 'set_node_value' service call.

    This function validates the provided `node_id` against SENSOR_DEFINITIONS
    to ensure it's a settable 'number' entity. It then validates the `value`
    against the node's configured type, range, and step. If all validations
    pass, it delegates the set operation to the HdgDataUpdateCoordinator.
    """
    node_id_input = call.data.get(ATTR_NODE_ID)
    value_to_set_raw = call.data.get(ATTR_VALUE)

    node_id_str, value_to_set = _validate_service_call_input(call)
    _LOGGER.debug(
        f"Service '{SERVICE_SET_NODE_VALUE}': node_id='{node_id_input}' (base='{node_id_str}'), value='{value_to_set}'"
    )

    sensor_def_for_node = _find_settable_sensor_definition(node_id_str)

    # Prepare for logging and validation using found sensor_def.
    api_node_id_with_suffix_for_log = sensor_def_for_node.get("hdg_node_id", node_id_str)
    _LOGGER.debug(
        f"Node ID '{node_id_str}': Found SensorDefinition: {sensor_def_for_node}. "
        f"API Node ID (log): {api_node_id_with_suffix_for_log}"
    )
    entity_name_for_log = sensor_def_for_node.get("translation_key", node_id_str)

    # Extract validation parameters from sensor_def.
    node_type = sensor_def_for_node.get("setter_type")
    min_val = sensor_def_for_node.get("setter_min_val")
    max_val = sensor_def_for_node.get("setter_max_val")
    node_step = sensor_def_for_node.get("setter_step")

    validated_value = _coerce_and_validate_value_type(value_to_set, node_type, entity_name_for_log)

    # Perform range and step validation if the value is numeric
    if isinstance(validated_value, (int, float)):
        _validate_value_range_and_step(
            validated_value=validated_value,
            min_val_def=min_val,
            max_val_def=max_val,
            node_step_def=node_step,
            entity_name_for_log=entity_name_for_log,
            node_id_str_for_log=node_id_str,
            original_value_to_set_for_log=value_to_set,
        )
        # If _validate_value_range_and_step did not raise an exception, validation passed.
        # Log context if validation failed (it would have raised ServiceValidationError)
        # This debug log is now less critical here as the helper raises directly.
        # Consider if it's still needed or if the helper's logging is sufficient.
        if _LOGGER.isEnabledFor(logging.DEBUG):  # pragma: no cover
            _LOGGER.debug(
                f"Validation context: input_node_id='{node_id_input}', value_to_set='{value_to_set}', "
                f"sensor_def={sensor_def_for_node}, validated_value={validated_value}"
            )

    # Attempt to set the value via the coordinator.
    try:
        success = await coordinator.async_set_node_value_if_changed(
            node_id=node_id_str,  # Base node ID.
            new_value_to_set=validated_value,  # Type-coerced and validated value.
            entity_name_for_log=entity_name_for_log,
        )
        if not success:  # Coordinator reported API failure (not a connection error).
            _LOGGER.error(
                f"Failed to set node '{entity_name_for_log}' (ID: {node_id_str}). Coordinator API failure."
            )
            raise HomeAssistantError(  # Raise HA error to signal service failure.
                f"Failed to set node '{entity_name_for_log}' (ID: {node_id_str}). API call failed."
            )
    except HdgApiError as err:  # Catch specific API client errors.
        _LOGGER.error(f"API error setting node '{entity_name_for_log}' (ID: {node_id_str}): {err}")
        raise HomeAssistantError(
            f"API error setting node '{entity_name_for_log}' (ID: {node_id_str}): {err}"
        ) from err
    except Exception as err:  # Catch any other unexpected errors.
        _LOGGER.exception(
            f"Unexpected error setting node '{entity_name_for_log}' (ID: {node_id_str}): {err}"
        )
        raise HomeAssistantError(
            f"Unexpected error setting node '{entity_name_for_log}' (ID: {node_id_str}): {err}"
        ) from err


async def async_handle_get_node_value(
    hass: HomeAssistant, coordinator: HdgDataUpdateCoordinator, call: ServiceCall
) -> Dict[str, Any]:
    """Handle 'get_node_value' service call. Returns raw string value from coordinator cache."""
    node_id_input = call.data.get(ATTR_NODE_ID)

    # Validate presence of required 'node_id' parameter.
    if node_id_input is None:
        _LOGGER.error(f"Service '{SERVICE_GET_NODE_VALUE}' missing '{ATTR_NODE_ID}'.")
        raise ServiceValidationError(f"'{ATTR_NODE_ID}' required for {SERVICE_GET_NODE_VALUE}.")

    node_id_str = str(node_id_input).strip()  # Standardize node_id.
    _LOGGER.debug(
        f"Service '{SERVICE_GET_NODE_VALUE}': node_id='{node_id_input}' (base='{node_id_str}')"
    )

    # Check if coordinator data is initialized.
    if coordinator.data is None:
        _LOGGER.warning(
            f"Coordinator data not initialized. Cannot get value for node '{node_id_str}'."
        )
        return {  # Return error status if data unavailable.
            "node_id": node_id_str,
            "value": None,
            "status": "coordinator_data_unavailable",
            "error": "Coordinator data store not initialized.",
        }

    # Retrieve value if node_id exists in coordinator data.
    if node_id_str in coordinator.data:
        value = coordinator.data[node_id_str]
        _LOGGER.debug(f"Node '{node_id_str}' found in coordinator. Raw value: '{value}'")
        return {"node_id": node_id_str, "value": value, "status": "found"}
    else:  # Node not found in coordinator data.
        _LOGGER.warning(f"Node '{node_id_str}' not found in coordinator data.")
        _LOGGER.debug(  # Log sample of available keys for debugging.
            f"Attempted find '{node_id_str}'. Available keys (sample): {list(coordinator.data.keys())[:20]}"
        )
        return {  # Return not_found status.
            "node_id": node_id_str,
            "value": None,
            "status": "not_found",
            "error": f"Node ID '{node_id_str}' not found in coordinator's data.",
        }
