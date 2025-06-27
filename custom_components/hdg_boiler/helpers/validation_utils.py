"""Validation utility functions for HDG Bavaria Boiler."""

from __future__ import annotations

__version__ = "0.1.2"

import logging

from decimal import Decimal, InvalidOperation
from typing import Any

from homeassistant.core import ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..const import (
    ATTR_NODE_ID,
    ATTR_VALUE,
    DOMAIN,
    SERVICE_GET_NODE_VALUE,
    SERVICE_SET_NODE_VALUE,
)

_LOGGER = logging.getLogger(DOMAIN)


def validate_service_call_input(call: ServiceCall) -> tuple[str, Any]:
    """Validate and extract node_id and value from the service call.

    This function ensures that the service call data contains the necessary
    `node_id` and `value` attributes for the `set_node_value` service.
    It raises a `ServiceValidationError` if either of these fields is missing,
    preventing further processing of an invalid service call.
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


def validate_get_node_service_call(call: ServiceCall) -> str:
    """Validate and extract node_id from the get_node_value service call.

    This function ensures that the service call data for the `get_node_value`
    service contains the required `node_id` attribute. It raises a
    `ServiceValidationError` if the field is missing.
    """
    node_id_input = call.data.get(ATTR_NODE_ID)
    if node_id_input is None:
        _LOGGER.error(f"Service '{SERVICE_GET_NODE_VALUE}' missing '{ATTR_NODE_ID}'.")
        raise ServiceValidationError(
            f"'{ATTR_NODE_ID}' required for {SERVICE_GET_NODE_VALUE}."
        )
    return str(node_id_input).strip()


def safe_float_convert(
    val_to_convert: Any, val_name: str, entity_name_for_log: str | None = None
) -> tuple[bool, float | None, str]:
    """Safely convert a value to a float, providing detailed error information.

    This function attempts to convert the given `val_to_convert` to a float.
    It's designed to be used when validating configuration values (like min/max/step
    from SENSOR_DEFINITIONS) that are expected to be numeric.

    Returns:
        A tuple: (success_flag, converted_float_value_or_None, error_message_string).
        `success_flag` is True if conversion was successful, False otherwise.
        `error_message_string` contains a descriptive error if conversion failed.

    """
    log_prefix = f"Entity '{entity_name_for_log}': " if entity_name_for_log else ""
    if val_to_convert is None:
        _LOGGER.error(f"{log_prefix}Config error: {val_name} is None.")
        return False, None, f"Config error: {val_name} is None."
    try:
        return True, float(val_to_convert), ""
    except (ValueError, TypeError) as e:
        _LOGGER.error(
            f"{log_prefix}Config error: {val_name} '{val_to_convert}' not valid number: {e}"
        )
        return (
            False,
            None,
            f"Config error: {val_name} '{val_to_convert}' not valid number.",
        )


def coerce_value_to_numeric_type(
    value_to_set: Any, node_type: str | None, entity_name_for_log: str
) -> int | float:
    """Coerce input value to the target numeric type (int or float) based on setter_type.

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
        if node_type in ["float1", "float2"]:
            return float(value_to_set)
        else:
            # This case should ideally be caught by other validation before this,
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
    """Perform step validation using Decimal objects for precision.

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
        _LOGGER.critical(
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
    else:
        decimal_epsilon = Decimal("1e-9")
        remainder = (val_decimal - min_val_decimal) % step_decimal

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


def validate_value_range_and_step(
    coerced_numeric_value: int | float,  # Type-coerced value
    min_val_def: Any,  # Raw definition value for min
    max_val_def: Any,  # Raw definition value for max
    node_step_def: Any,  # Raw definition value for step
    entity_name_for_log: str,
    node_id_str_for_log: str,
    original_value_to_set_for_log: Any,
) -> None:
    """Validate the numeric value against configured min, max, and step.

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
    numeric_value_for_check = float(coerced_numeric_value)
    # Validate against 'setter_min_val' if defined.
    if min_val_def is not None:
        conversion_ok, min_val_float, conv_error_msg = safe_float_convert(
            min_val_def, "setter_min_val", entity_name_for_log
        )
        if not conversion_ok:
            raise ServiceValidationError(
                f"Configuration error for node '{entity_name_for_log}': {conv_error_msg}"
            )
        if min_val_float is not None and numeric_value_for_check < min_val_float:
            raise ServiceValidationError(
                f"Value {numeric_value_for_check} is below the minimum of {min_val_float} for node '{entity_name_for_log}'."
            )

    # Validate against 'setter_max_val' if defined.
    if max_val_def is not None:
        conversion_ok, max_val_float, conv_error_msg = safe_float_convert(
            max_val_def, "setter_max_val", entity_name_for_log
        )
        if not conversion_ok:
            raise ServiceValidationError(
                f"Configuration error for node '{entity_name_for_log}': {conv_error_msg}"
            )
        if max_val_float is not None and numeric_value_for_check > max_val_float:
            raise ServiceValidationError(
                f"Value {numeric_value_for_check} is above the maximum of {max_val_float} for node '{entity_name_for_log}'."
            )

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
            error_message = f"Invalid numeric format for step validation (min, step, or value): {dec_err}"
            _LOGGER.error(
                f"{error_message} for node '{entity_name_for_log}'. Input: value='{original_value_to_set_for_log}', min='{min_val_def}', step='{node_step_def}'."
            )
            raise ServiceValidationError(
                f"Step validation failed for node '{entity_name_for_log}' due to invalid number format. Reason: {error_message}"
            ) from dec_err
