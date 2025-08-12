"""Service handlers for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.2.0"
__all__ = ["async_handle_set_node_value", "async_handle_get_node_value"]

import logging
from typing import Any, cast

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DEFAULT_SET_VALUE_DEBOUNCE_DELAY_S, DOMAIN
from .coordinator import HdgDataUpdateCoordinator
from .exceptions import HdgApiError
from .helpers.parsers import format_value_for_api
from .helpers.validation_utils import (
    coerce_value_to_numeric_type,
    validate_get_node_service_call,
    validate_set_node_service_call,
    validate_value_range_and_step,
)
from .models import SensorDefinition
from .registry import HdgEntityRegistry


_LOGGER = logging.getLogger(DOMAIN)


def _get_settable_definition(
    node_id: str, hdg_entity_registry: HdgEntityRegistry
) -> SensorDefinition:
    """Get the entity definition for a settable number entity."""
    if definition := hdg_entity_registry.get_settable_number_definition_by_base_node_id(
        node_id
    ):
        return definition
    else:
        raise ServiceValidationError(
            f"Node ID '{node_id}' is not a valid settable 'number' entity."
        )


def _validate_and_coerce_value(
    raw_value: Any, definition: SensorDefinition, node_id: str
) -> int | float:
    """Validate and coerce the raw value to the correct numeric type."""
    entity_name = definition.get("translation_key", node_id)
    node_type = definition.get("setter_type")

    coerced_value = coerce_value_to_numeric_type(raw_value, node_type, entity_name)
    validate_value_range_and_step(
        coerced_numeric_value=coerced_value,
        min_val_def=definition.get("setter_min_val"),
        max_val_def=definition.get("setter_max_val"),
        node_step_def=definition.get("setter_step"),
        entity_name_for_log=entity_name,
    )
    return coerced_value


def _validate_and_prepare_node_value(
    call: ServiceCall, hdg_entity_registry: HdgEntityRegistry
) -> tuple[str, str, str]:
    """Validate service call input, find definition, and prepare value."""
    node_id, raw_value = validate_set_node_service_call(call)
    _LOGGER.debug("Service set_node_value: id='%s', value='%s'", node_id, raw_value)

    definition = _get_settable_definition(node_id, hdg_entity_registry)
    coerced_value = _validate_and_coerce_value(raw_value, definition, node_id)

    entity_name = definition.get("translation_key", node_id)
    node_type = definition.get("setter_type")
    api_value = format_value_for_api(coerced_value, cast(str, node_type))

    return node_id, api_value, entity_name


async def async_handle_set_node_value(
    hass: HomeAssistant,
    coordinator: HdgDataUpdateCoordinator,
    hdg_entity_registry: HdgEntityRegistry,
    call: ServiceCall,
) -> None:
    """Handle the 'set_node_value' service call."""
    try:
        node_id, value_to_set, entity_name = _validate_and_prepare_node_value(
            call, hdg_entity_registry
        )
        success = await coordinator.async_set_node_value(
            node_id=node_id,
            value=value_to_set,
            entity_name_for_log=entity_name,
            debounce_delay=DEFAULT_SET_VALUE_DEBOUNCE_DELAY_S,
        )
        if not success:
            raise HomeAssistantError(f"Failed to set node '{entity_name}' ({node_id}).")
    except (HdgApiError, HomeAssistantError, ServiceValidationError) as err:
        _LOGGER.error("Error during service call to set node value: %s", err)
        raise
    except Exception as err:
        _LOGGER.exception("Unexpected error setting node value.")
        raise HomeAssistantError("Unexpected error setting node value.") from err


async def async_handle_get_node_value(
    hass: HomeAssistant,
    coordinator: HdgDataUpdateCoordinator,
    hdg_entity_registry: HdgEntityRegistry,
    call: ServiceCall,
) -> dict[str, Any]:
    """Handle the 'get_node_value' service call."""
    node_id = validate_get_node_service_call(call)
    _LOGGER.debug("Service get_node_value: node_id='%s'", node_id)

    if coordinator.data is None:
        raise ServiceValidationError("Coordinator data not available.")

    if (value := coordinator.data.get(node_id)) is not None:
        return {"node_id": node_id, "value": value}

    raise ServiceValidationError(f"Node ID '{node_id}' not found in coordinator data.")
