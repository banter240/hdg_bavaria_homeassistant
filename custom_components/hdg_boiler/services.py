"""
Service handlers for the HDG Bavaria Boiler integration.

This module implements the logic for custom Home Assistant services exposed by
the HDG Bavaria Boiler integration. These services allow users to directly
interact with the boiler by setting specific node values (e.g., temperature setpoints)
and retrieving current raw values for any monitored node.
"""

__version__ = "0.8.5"
import logging
from typing import Any, cast

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import (
    ATTR_NODE_ID,
    DOMAIN,
    SERVICE_GET_NODE_VALUE,
    SERVICE_SET_NODE_VALUE,
)
from .coordinator import HdgDataUpdateCoordinator
from .definitions import (
    SENSOR_DEFINITIONS,
    SensorDefinition,
)
from .exceptions import HdgApiError
from .helpers.parsing_utils import (
    format_value_for_api,
)
from .helpers.string_utils import (
    extract_base_node_id,
)
from .helpers.validation_utils import (
    coerce_value_to_numeric_type,
    validate_get_node_service_call,
    validate_service_call_input,
    validate_value_range_and_step,
)

_LOGGER = logging.getLogger(DOMAIN)


def _build_sensor_definitions_by_base_node_id() -> dict[str, list[SensorDefinition]]:
    """
    Build an index of sensor definitions keyed by their base HDG node ID.

    This allows quick lookup of all definitions associated with a specific base node ID.
    The index is used by `_find_settable_sensor_definition` to efficiently locate
    the correct definition for a `set_node_value` service call.
    """
    index: dict[str, list[SensorDefinition]] = {}

    for definition_dict in SENSOR_DEFINITIONS.values():
        definition = cast(SensorDefinition, definition_dict)
        # Ensure hdg_node_id exists and is a string before attempting to extract
        # the base ID. This prevents errors if a definition is malformed.
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


# Pre-build the index at module load time for efficiency.
SENSOR_DEFINITIONS_BY_BASE_NODE_ID = _build_sensor_definitions_by_base_node_id()


def _find_settable_sensor_definition(node_id_str: str) -> SensorDefinition:
    """
    Find and return the SensorDefinition for a settable 'number' node.

    Queries the cached `SENSOR_DEFINITIONS_BY_BASE_NODE_ID` index to find definitions
    matching the base node ID. It then filters for definitions where `ha_platform`
    is "number" and `setter_type` is defined, returning the single matching definition.

    Raises:
        ServiceValidationError: If no matching settable 'number' definition is found,
                                or if multiple conflicting definitions are found for the
                                same base node ID.

    Args:
        node_id_str: The base HDG node ID to search for.
    """
    # Retrieve all definitions associated with the base node ID.
    definitions_for_base = SENSOR_DEFINITIONS_BY_BASE_NODE_ID.get(node_id_str, [])
    settable_definitions = [
        d
        for d in definitions_for_base
        if d.get("ha_platform") == "number" and d.get("setter_type")
    ]

    # Handle cases where no suitable definition is found.
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

    # Handle cases where multiple conflicting definitions are found.
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

    Args:
        hass: The HomeAssistant instance.
        coordinator: The HdgDataUpdateCoordinator instance.
        call: The ServiceCall object containing `node_id` and `value`.

    Raises:
        ServiceValidationError: If input validation fails or configuration is incorrect.
        HomeAssistantError: If the API call fails or the coordinator reports an error.
    """
    node_id_input = call.data.get(ATTR_NODE_ID)
    node_id_str, value_to_set_raw = validate_service_call_input(call)
    _LOGGER.debug(
        f"Service '{SERVICE_SET_NODE_VALUE}': node_id='{node_id_input}' (base='{node_id_str}'), value='{value_to_set_raw}'"
    )

    sensor_def_for_node = _find_settable_sensor_definition(node_id_str)
    # Use translation_key for logging if available, otherwise the raw node_id.
    entity_name_for_log = sensor_def_for_node.get("translation_key", node_id_str)

    node_type = sensor_def_for_node.get("setter_type")
    min_val_def = sensor_def_for_node.get("setter_min_val")
    max_val_def = sensor_def_for_node.get("setter_max_val")
    node_step_def = sensor_def_for_node.get("setter_step")

    # 1. Coerce the input value to the expected numeric type (int or float).
    coerced_numeric_value = coerce_value_to_numeric_type(
        value_to_set_raw, node_type, entity_name_for_log
    )

    # 2. Validate the coerced numeric value against the defined range and step.
    validate_value_range_and_step(
        coerced_numeric_value=coerced_numeric_value,
        min_val_def=min_val_def,
        max_val_def=max_val_def,
        node_step_def=node_step_def,
        entity_name_for_log=entity_name_for_log,
        node_id_str_for_log=node_id_str,
        original_value_to_set_for_log=value_to_set_raw,
    )

    # 3. Format the validated numeric value into the string expected by the HDG API.
    try:
        # node_type is confirmed to be non-None and valid by _find_settable_sensor_definition
        api_value_to_send_str = format_value_for_api(
            coerced_numeric_value, cast(str, node_type)
        )
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
            raise HomeAssistantError(
                f"Failed to set node '{entity_name_for_log}' (ID: {node_id_str}). Coordinator reported failure."
            )
    except HdgApiError as err:
        _LOGGER.error(
            f"API error setting node '{entity_name_for_log}' (ID: {node_id_str}): {err}"
        )
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
) -> dict[str, Any]:
    """# sourcery skip: extract-method
    Handle the 'get_node_value' service call.

    Retrieves the current raw string value for a specified node ID from the
    coordinator's internal data cache and returns it.
    Raises ServiceValidationError if the required `node_id` is missing.

    Args:
        hass: The HomeAssistant instance.
        coordinator: The HdgDataUpdateCoordinator instance.
        call: The ServiceCall object containing `node_id`.

    Returns:
        A dictionary containing the `node_id`, its `value` (or None),
        and a `status` string.
    """
    node_id_input = call.data.get(ATTR_NODE_ID)
    node_id_str = validate_get_node_service_call(call)
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
        _LOGGER.debug(
            f"Node '{node_id_str}' found in coordinator. Raw value: '{value}'"
        )
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
