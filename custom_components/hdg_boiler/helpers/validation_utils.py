"""Validation utility functions for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.2.0"

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from homeassistant.core import ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..const import ATTR_NODE_ID, ATTR_VALUE, DOMAIN

_LOGGER = logging.getLogger(DOMAIN)

__all__ = [
    "validate_set_node_service_call",
    "validate_get_node_service_call",
    "coerce_value_to_numeric_type",
    "validate_value_range_and_step",
]


def _validate_and_get_node_id(call: ServiceCall) -> str:
    """Extract and validate node_id from a service call."""
    node_id_input = call.data.get(ATTR_NODE_ID)
    if node_id_input is None:
        raise ServiceValidationError(f"'{ATTR_NODE_ID}' is a required field.")
    return str(node_id_input).strip()


def validate_set_node_service_call(call: ServiceCall) -> tuple[str, Any]:
    """Validate and extract node_id and value from the set_node_value service call."""
    node_id = _validate_and_get_node_id(call)
    value_to_set = call.data.get(ATTR_VALUE)

    if value_to_set is None:
        raise ServiceValidationError(f"'{ATTR_VALUE}' is a required field.")

    return node_id, value_to_set


def validate_get_node_service_call(call: ServiceCall) -> str:
    """Validate and extract node_id from the get_node_value service call."""
    return _validate_and_get_node_id(call)


def _safe_convert_to_decimal(value: Any, param_name: str, entity_name: str) -> Decimal:
    """Safely convert a value to Decimal, raising ServiceValidationError on failure."""
    if value is None:
        raise ServiceValidationError(
            f"Configuration error for '{entity_name}': '{param_name}' cannot be None."
        )
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ServiceValidationError(
            f"Configuration error for '{entity_name}': Invalid number format for "
            f"'{param_name}' ('{value}')."
        ) from exc


def _validate_range(
    value: Decimal, min_val: Decimal | None, max_val: Decimal | None, entity_name: str
) -> None:
    """Validate that a value is within the optional min/max range."""
    if min_val is not None and value < min_val:
        raise ServiceValidationError(
            f"Value {value} is below the minimum of {min_val} for '{entity_name}'."
        )
    if max_val is not None and value > max_val:
        raise ServiceValidationError(
            f"Value {value} is above the maximum of {max_val} for '{entity_name}'."
        )


def _validate_step(
    value: Decimal, min_val: Decimal, step: Decimal, entity_name: str
) -> None:
    """Validate that a value respects the defined step, using Decimal for precision."""
    if step < Decimal(0):
        raise ServiceValidationError(
            f"Configuration error for '{entity_name}': Step must be non-negative."
        )
    if step == Decimal(0):
        if value != min_val:
            raise ServiceValidationError(
                f"Value {value} not allowed for '{entity_name}'. With step 0, "
                f"only min_value {min_val} is valid."
            )
        return

    # Use an epsilon for robust floating-point comparison
    epsilon = Decimal("1e-9")
    remainder = (value - min_val) % step

    is_close_to_zero = abs(remainder) < epsilon
    is_close_to_step = abs(remainder - step) < epsilon

    if not (is_close_to_zero or is_close_to_step):
        raise ServiceValidationError(
            f"Value {value} for '{entity_name}' is not a valid step from {min_val} "
            f"with step {step}. Remainder: {remainder}"
        )


def validate_value_range_and_step(
    coerced_numeric_value: int | float,
    min_val_def: Any,
    max_val_def: Any,
    node_step_def: Any,
    entity_name_for_log: str,
) -> None:
    """Validate the numeric value against configured min, max, and step."""
    val_decimal = _safe_convert_to_decimal(
        coerced_numeric_value, "value", entity_name_for_log
    )

    min_val_decimal = (
        _safe_convert_to_decimal(min_val_def, "setter_min_val", entity_name_for_log)
        if min_val_def is not None
        else None
    )
    max_val_decimal = (
        _safe_convert_to_decimal(max_val_def, "setter_max_val", entity_name_for_log)
        if max_val_def is not None
        else None
    )

    _validate_range(val_decimal, min_val_decimal, max_val_decimal, entity_name_for_log)

    if node_step_def is not None and min_val_decimal is not None:
        step_decimal = _safe_convert_to_decimal(
            node_step_def, "setter_step", entity_name_for_log
        )
        _validate_step(val_decimal, min_val_decimal, step_decimal, entity_name_for_log)


def coerce_value_to_numeric_type(
    value_to_set: Any, node_type: str | None, entity_name_for_log: str
) -> int | float:
    """Coerce input value to the target numeric type (int or float)."""
    try:
        if node_type == "int":
            temp_float = float(value_to_set)
            if temp_float != int(temp_float):
                raise ValueError("Value is not a whole number.")
            return int(temp_float)
        if node_type in ["float1", "float2"]:
            return float(value_to_set)
        raise ValueError(f"Unknown or missing setter_type '{node_type}'.")
    except (ValueError, TypeError) as exc:
        raise ServiceValidationError(
            f"Value '{value_to_set}' is not a valid '{node_type}' for '{entity_name_for_log}'."
        ) from exc
