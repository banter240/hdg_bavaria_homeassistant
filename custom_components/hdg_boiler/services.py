"""
Service handlers for the HDG Bavaria Boiler integration.

This module defines the logic for custom services exposed by the integration,
such as setting or getting specific node values on the HDG boiler.
"""

__version__ = "0.6.0"

import logging
from typing import Any, Dict, Union, cast

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .api import HdgApiError  # Custom API error for specific error handling.
from .coordinator import HdgDataUpdateCoordinator
from .const import (
    ATTR_NODE_ID,
    ATTR_VALUE,
    DOMAIN,
    SENSOR_DEFINITIONS,
    SERVICE_SET_NODE_VALUE,
    SERVICE_GET_NODE_VALUE,
    SensorDefinition,  # TypedDict for items in SENSOR_DEFINITIONS
)

_LOGGER = logging.getLogger(DOMAIN)


async def async_handle_set_node_value(
    hass: HomeAssistant,
    coordinator: HdgDataUpdateCoordinator,
    call: ServiceCall,
) -> None:
    """
    Handle the service call to set an HDG node value.

    This service validates the input against parameters defined within SENSOR_DEFINITIONS
    for the specified node before attempting to set the value via the coordinator.
    The node_id is expected to be the base ID (e.g., "6022") and the value will be
    type-checked and range-checked based on the 'setter_*' attributes in its SensorDefinition.
    """
    node_id_input = call.data.get(ATTR_NODE_ID)
    value_to_set = call.data.get(ATTR_VALUE)

    # Ensure both required parameters are provided in the service call.
    if node_id_input is None or value_to_set is None:
        _LOGGER.error(
            f"Service '{SERVICE_SET_NODE_VALUE}' called with missing '{ATTR_NODE_ID}' or '{ATTR_VALUE}'."
        )
        raise ServiceValidationError(
            f"'{ATTR_NODE_ID}' and '{ATTR_VALUE}' are required fields for the {SERVICE_SET_NODE_VALUE} service."
        )

    # Standardize the node_id to a string and remove leading/trailing whitespace.
    # The service expects the base HDG node ID (e.g., "6022") without any API suffixes (like 'T').
    node_id_str = str(node_id_input).strip()
    _LOGGER.debug(
        f"Service '{SERVICE_SET_NODE_VALUE}' called. Input node_id: '{node_id_input}' (processed as base ID: '{node_id_str}'), value: '{value_to_set}'"
    )

    # Find the SensorDefinition for the given node_id_str.
    # The definition must be for the "number" platform and contain necessary setter parameters.
    sensor_def_for_node: SensorDefinition | None = None
    for definition_dict in SENSOR_DEFINITIONS.values():
        definition = cast(SensorDefinition, definition_dict)
        # Compare base node IDs (stripping potential suffixes from SENSOR_DEFINITIONS's 'hdg_node_id').
        if (
            definition.get("hdg_node_id", "").rstrip("TUVWXY") == node_id_str
            and definition.get("ha_platform") == "number"
            and definition.get("setter_type")
        ):  # 'setter_type' presence indicates a settable number entity.
            sensor_def_for_node = definition
            break

    if not sensor_def_for_node:
        _LOGGER.error(
            f"Node ID '{node_id_str}' is not configured as a settable 'number' entity "
            "with necessary setter parameters (setter_type, setter_min_val, etc.) in SENSOR_DEFINITIONS. "
            "This node cannot be set via this service."
        )
        raise ServiceValidationError(
            f"Node ID '{node_id_str}' is not configured as a settable 'number' entity in SENSOR_DEFINITIONS."
        )

    # For logging context, get the full API node ID (potentially with suffix) from the definition.
    api_node_id_with_suffix_for_log = sensor_def_for_node.get("hdg_node_id", node_id_str)
    _LOGGER.debug(
        f"For input node ID '{node_id_str}': Found matching SensorDefinition: {sensor_def_for_node}. "
        f"Full API node ID from sensor_def (for logging context): {api_node_id_with_suffix_for_log}"
    )

    # Use the translation_key from sensor_def for logging if available, otherwise use the input node ID.
    # This provides a more user-friendly name in logs.
    entity_name_for_log = sensor_def_for_node.get("translation_key", node_id_str)

    # Validate the input value against the node's configuration (type, min, max, step)
    # sourced from the SensorDefinition.
    node_type = sensor_def_for_node.get("setter_type")
    min_val = sensor_def_for_node.get("setter_min_val")
    max_val = sensor_def_for_node.get("setter_max_val")
    node_step = sensor_def_for_node.get("setter_step")
    validated_value: Union[int, float, str, None] = None  # Stores the type-coerced value.
    is_valid = True
    error_message = ""

    try:
        # Coerce the input value to the expected numeric type.
        if node_type == "int":
            temp_float = float(
                value_to_set
            )  # Attempt conversion to float first for robust parsing.
            if temp_float != int(temp_float):  # Check if it's a whole number.
                is_valid = False
                error_message = (
                    f"Value '{value_to_set}' is not a whole number for integer type node."
                )
            else:
                validated_value = int(temp_float)
        elif node_type == "float1":  # Expects one decimal place.
            validated_value = round(float(value_to_set), 1)
        elif node_type == "float2":  # Expects two decimal places.
            validated_value = round(float(value_to_set), 2)
        else:  # Default to string if no specific numeric type; unlikely for configured setters.
            _LOGGER.warning(
                f"Node '{entity_name_for_log}' has an unexpected setter_type '{node_type}'. Treating value as string."
            )
            validated_value = str(value_to_set)
    except ValueError:
        is_valid = False
        error_message = f"Value '{value_to_set}' could not be converted to the expected numeric type '{node_type}'."

    # Perform range and step validation if the value was successfully type-coerced.
    if is_valid and validated_value is not None and node_type in ["int", "float1", "float2"]:
        numeric_value_for_check = float(validated_value)  # Ensure it's float for comparisons.

        if min_val is not None and numeric_value_for_check < float(min_val):
            is_valid = False
            error_message = f"Value {numeric_value_for_check} is less than minimum {min_val}."
        if is_valid and max_val is not None and numeric_value_for_check > float(max_val):
            is_valid = False
            error_message = f"Value {numeric_value_for_check} is greater than maximum {max_val}."

        # Validate step if min_val and node_step are defined.
        if is_valid and node_step is not None and min_val is not None:
            float_step = float(node_step)
            # A step of 0 might be a device-specific quirk, often meaning only min_val is allowed.
            if float_step == 0:
                if numeric_value_for_check != float(min_val):
                    is_valid = False
                    error_message = f"Value {numeric_value_for_check} is not allowed. With step {float_step}, only {min_val} is valid."
            else:
                # Check if (value - min_val) is a multiple of step, accounting for floating-point inaccuracies.
                num_steps_float = (numeric_value_for_check - float(min_val)) / float_step
                # Use a small tolerance (epsilon) for floating point comparisons.
                if (
                    abs(num_steps_float - round(num_steps_float)) > 1e-9
                ):  # Epsilon for float comparison
                    is_valid = False
                    error_message = f"Value {numeric_value_for_check} does not meet step requirement of {float_step} from minimum {min_val}."

    if not is_valid:
        full_error_message = (
            f"Validation failed for node '{entity_name_for_log}' (API Input ID: {node_id_str}) with value '{value_to_set}'. "
            f"Reason: {error_message}"
        )
        _LOGGER.error(full_error_message)
        _LOGGER.debug(
            f"Validation context: node_id_input='{node_id_input}', value_to_set='{value_to_set}', "
            f"node_id_str='{node_id_str}', sensor_def_for_node={sensor_def_for_node}, "
            f"api_node_id_with_suffix_for_log='{api_node_id_with_suffix_for_log}', validated_value={validated_value}"
        )
        raise ServiceValidationError(full_error_message)

    try:
        # Call the coordinator to set the value. The coordinator handles string conversion
        # for the API and the "if_changed" logic to avoid redundant API calls.
        # The node_id_str (base ID) is used for the coordinator method.
        # The validated_value (potentially numeric) is passed; the coordinator will stringify it for the API.
        success = await coordinator.async_set_node_value_if_changed(
            node_id=node_id_str,
            new_value_to_set=validated_value,
            entity_name_for_log=entity_name_for_log,
        )
        if not success:
            # The coordinator's method should have logged details of the API failure.
            # Raise an error here to inform Home Assistant that the service call ultimately failed.
            _LOGGER.error(
                f"Failed to set HDG node '{entity_name_for_log}' (Node ID: {node_id_str}) via API. "
                "The coordinator reported a failure to the HDG device."
            )
            raise HomeAssistantError(
                f"Failed to set HDG node '{entity_name_for_log}' (Node ID: {node_id_str}). API call failed."
            )
    except HdgApiError as err:
        _LOGGER.error(
            f"API error while trying to set node '{entity_name_for_log}' (Node ID: {node_id_str}): {err}"
        )
        raise HomeAssistantError(
            f"API error setting HDG node '{entity_name_for_log}' (Node ID: {node_id_str}): {err}"
        ) from err
    except Exception as err:  # Catch any other unexpected errors during the process.
        _LOGGER.exception(
            f"Unexpected error while setting node '{entity_name_for_log}' (Node ID: {node_id_str}): {err}"
        )
        raise HomeAssistantError(
            f"Unexpected error setting HDG node '{entity_name_for_log}' (Node ID: {node_id_str}): {err}"
        ) from err


async def async_handle_get_node_value(
    hass: HomeAssistant, coordinator: HdgDataUpdateCoordinator, call: ServiceCall
) -> Dict[str, Any]:
    """
    Handle the service call to get an HDG node value from the coordinator's internal state.

    Returns the raw string value as stored by the coordinator, which is how the API
    typically provides it before any type parsing by sensor entities.
    """
    node_id_input = call.data.get(ATTR_NODE_ID)

    if node_id_input is None:
        _LOGGER.error(f"Service '{SERVICE_GET_NODE_VALUE}' called with missing '{ATTR_NODE_ID}'.")
        raise ServiceValidationError(
            f"'{ATTR_NODE_ID}' is a required field for the {SERVICE_GET_NODE_VALUE} service."
        )

    # Standardize the node_id to a string and remove leading/trailing whitespace.
    # The coordinator stores data with base node IDs (without T/U/V/W/X/Y suffixes).
    node_id_str = str(node_id_input).strip()
    _LOGGER.debug(
        f"Service '{SERVICE_GET_NODE_VALUE}' called. Input node_id: '{node_id_input}' (searching for base ID: '{node_id_str}')"
    )

    if coordinator.data is None:  # Check if coordinator.data itself is None
        _LOGGER.warning(
            f"Coordinator data store is not initialized. Cannot retrieve value for node '{node_id_str}'."
        )
        return {"node_id": node_id_str, "value": None, "status": "coordinator_data_unavailable"}

    if node_id_str in coordinator.data:
        value = coordinator.data[node_id_str]
        _LOGGER.debug(f"Node '{node_id_str}' found in coordinator data. Raw value: '{value}'")
        return {"node_id": node_id_str, "value": value, "status": "found"}
    else:
        _LOGGER.warning(f"Node '{node_id_str}' not found in coordinator's current data store.")
        # Log a sample of available keys for easier debugging if a node is not found.
        _LOGGER.debug(
            f"Attempted to find '{node_id_str}'. Available keys (sample): {list(coordinator.data.keys())[:20]}"
        )
        return {"node_id": node_id_str, "value": None, "status": "not_found"}
