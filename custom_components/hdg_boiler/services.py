"""Service handlers for the HDG Bavaria Boiler integration.

This module implements the logic for custom Home Assistant services exposed by
the HDG Bavaria Boiler integration. These services allow users to directly
interact with the boiler by setting specific node values (e.g., temperature setpoints)
and retrieving current raw values for any monitored node.
"""

__version__ = "0.8.6"
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
from .registry import HdgEntityRegistry
from .exceptions import HdgApiError
from .helpers.parsers import (
    format_value_for_api,
)
from .helpers.validation_utils import (
    coerce_value_to_numeric_type,
    validate_get_node_service_call,
    validate_service_call_input,
    validate_value_range_and_step,
)

_LOGGER = logging.getLogger(DOMAIN)


async def async_handle_set_node_value(
    hass: HomeAssistant,
    coordinator: HdgDataUpdateCoordinator,
    hdg_entity_registry: HdgEntityRegistry,
    call: ServiceCall,
) -> None:
    """Handle the 'set_node_value' service call.

    This function validates the provided `node_id` against SENSOR_DEFINITIONS
    to ensure it's a settable 'number' entity. It then coerces the `value`
    to the expected numeric type, validates it against the node's configured
    range and step, formats it for the API, and finally delegates the set # sourcery skip: extract-method
    operation to the HdgDataUpdateCoordinator.

    Args:
        hass: The HomeAssistant instance.
        coordinator: The HdgDataUpdateCoordinator instance.
        hdg_entity_registry: The HdgEntityRegistry instance for accessing entity definitions.
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

    sensor_def_for_node = (
        hdg_entity_registry.get_settable_number_definition_by_base_node_id(node_id_str)
    )
    if not sensor_def_for_node:
        raise ServiceValidationError(
            f"Node ID '{node_id_str}' not settable. No valid settable 'number' definition found."
        )
    entity_name_for_log = sensor_def_for_node.get("translation_key", node_id_str)

    node_type = sensor_def_for_node.get("setter_type")
    min_val_def = sensor_def_for_node.get("setter_min_val")
    max_val_def = sensor_def_for_node.get("setter_max_val")
    node_step_def = sensor_def_for_node.get("setter_step")

    coerced_numeric_value = coerce_value_to_numeric_type(
        value_to_set_raw, node_type, entity_name_for_log
    )

    validate_value_range_and_step(
        coerced_numeric_value=coerced_numeric_value,
        min_val_def=min_val_def,
        max_val_def=max_val_def,
        node_step_def=node_step_def,
        entity_name_for_log=entity_name_for_log,
        node_id_str_for_log=node_id_str,
        original_value_to_set_for_log=value_to_set_raw,
    )

    try:
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

    try:
        success = await coordinator.async_set_node_value(
            node_id=node_id_str,
            value=api_value_to_send_str,
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
    except Exception as err:
        _LOGGER.exception(
            f"Unexpected error setting node '{entity_name_for_log}' (ID: {node_id_str}): {err}"
        )
        raise HomeAssistantError(
            f"Unexpected error setting node '{entity_name_for_log}' (ID: {node_id_str}): {err}"
        ) from err


async def async_handle_get_node_value(
    hass: HomeAssistant,
    coordinator: HdgDataUpdateCoordinator,
    hdg_entity_registry: HdgEntityRegistry,
    call: ServiceCall,
) -> dict[str, Any]:
    """Handle the 'get_node_value' service call.

    Retrieves the current raw string value for a specified node ID from the
    coordinator's internal data cache and returns it.
    Raises ServiceValidationError if the required `node_id` is missing.

    Args:
        hass: The HomeAssistant instance.
        coordinator: The HdgDataUpdateCoordinator instance.
        hdg_entity_registry: The HdgEntityRegistry instance for accessing entity definitions.
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
        raise ServiceValidationError(
            f"Coordinator data store not initialized. Cannot get value for node '{node_id_str}'."
        )

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
        raise ServiceValidationError(
            f"Node ID '{node_id_str}' not found in coordinator's data."
        )
