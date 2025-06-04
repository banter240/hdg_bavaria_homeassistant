"""
Platform for number entities for the HDG Bavaria Boiler integration.
This module creates and manages 'number' entities, enabling users to modify
numeric settings on their HDG Bavaria boiler. These entities handle state
updates from the data coordinator and implement debouncing for API calls
when setting new values to prevent overwhelming the boiler's API.
"""

from __future__ import annotations

__version__ = "0.8.49"

import functools
import logging
from typing import Any, cast

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .api import HdgApiClient, HdgApiError
from .const import (
    DOMAIN,
    NUMBER_SET_VALUE_DEBOUNCE_DELAY_S,
)
from .coordinator import HdgDataUpdateCoordinator
from .definitions import (
    SENSOR_DEFINITIONS,
    SensorDefinition,
)
from .entity import HdgNodeEntity
from .utils import (
    format_value_for_api,
    parse_float_from_string,
    parse_int_from_string,
    strip_hdg_node_suffix,
)

_LOGGER = logging.getLogger(DOMAIN)


class HdgBoilerNumber(HdgNodeEntity, NumberEntity):
    """
    Represents an HDG Bavaria Boiler number entity.

    Enables users to view and modify numeric settings on the boiler.
    It receives state updates from the HdgDataUpdateCoordinator and debounces
    API calls when a user sets a new value to avoid overwhelming the API.
    """

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        api_client: HdgApiClient,  # api_client is passed but not directly used by HdgBoilerNumber itself.
        # It's available if direct API calls were needed here,
        # but set operations are currently routed via the coordinator.
        entity_description: NumberEntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """
        Initialize the HDG Boiler number entity.

        Sets up the entity's unique ID, device information, and initializes
        mechanisms for debouncing API calls when the entity's value is set.

        Args:
            coordinator: The HdgDataUpdateCoordinator for managing entity data.
            api_client: The HdgApiClient instance (currently unused directly by this class).
            entity_description: Standard Home Assistant NumberEntityDescription.
            entity_definition: Custom entity definition from SENSOR_DEFINITIONS.
        """
        hdg_api_node_id_from_def = entity_definition["hdg_node_id"]
        super().__init__(
            coordinator=coordinator,
            node_id=strip_hdg_node_suffix(hdg_api_node_id_from_def),
            # Cast to dict[str, Any] to satisfy mypy, as TypedDict is compatible.
            entity_definition=cast(dict[str, Any], entity_definition),
        )

        self.entity_description = entity_description
        # self._api_client = api_client # Storing api_client if direct calls were needed.

        # Timer and generation tracking for debouncing set value calls.
        self._current_set_generation: int = 0
        self._pending_api_call_timer: CALLBACK_TYPE | None = None  # Correct type hint
        self._value_for_current_generation: Any | None = None

        self._attr_native_value: int | float | None = None
        self._update_number_state()

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
        """Update internal state from coordinator data."""
        self._attr_available = super().available

        if not self._attr_available:
            self._attr_native_value = None
            return

        raw_value_text = self.coordinator.data.get(self._node_id)
        self._attr_native_value = self._parse_value(raw_value_text)

    def _parse_value(self, raw_value_text: str | None) -> int | float | None:
        """Parse the raw string value from the API into an int or float.

        The method uses the 'setter_type' from the entity's definition to
        determine whether the native value should be an integer or a float.
        It handles strings that might include units or non-numeric characters.
        """
        if raw_value_text is None:
            return None
        cleaned_value = raw_value_text.strip()
        # Explicitly check for None after stripping, although the initial check should cover this.
        if cleaned_value is None:
            return None
        if not cleaned_value:
            return None

        setter_type = self._entity_definition.get("setter_type")

        if setter_type == "int":
            return parse_int_from_string(cleaned_value, self._node_id, self.entity_id)

        # Default to float parsing for other numeric setter types (e.g., 'float1', 'float2').
        # This ensures that values like "10.0" are treated as floats if not explicitly 'int'.
        parsed_float = parse_float_from_string(
            cleaned_value, self._node_id, self.entity_id
        )
        if parsed_float is None:
            _LOGGER.warning(
                f"Could not parse float for {self.entity_id} (node {self._node_id}) from raw value '{raw_value_text}' (cleaned: '{cleaned_value}')."
            )
            return None
        return parsed_float

    async def async_set_native_value(self, value: float) -> None:
        """
        Set the new native value for the number entity.

        This method is called by Home Assistant when the user changes the value
        in the UI. It initiates a debounced process to update the boiler via API.
        A generation counter is used to ensure that only the most recent value
        set by the user is actually sent to the boiler after the debounce delay.
        """
        self._current_set_generation += 1
        local_generation_for_job = self._current_set_generation
        self._value_for_current_generation = value

        _LOGGER.debug(
            f"async_set_native_value called for {self.entity_id} with value {value}. "
            f"Generation: {local_generation_for_job}. Debouncing for {NUMBER_SET_VALUE_DEBOUNCE_DELAY_S}s."
        )

        if self._pending_api_call_timer:
            # async_call_later returns a callable to cancel the timer
            if callable(self._pending_api_call_timer):
                self._pending_api_call_timer()  # Call the cancel callback directly
                _LOGGER.debug(
                    f"Successfully cancelled existing API call timer for {self.entity_id}."
                )
            else:
                # This case should ideally not happen if _pending_api_call_timer is always assigned correctly.
                _LOGGER.warning(
                    f"Cannot cancel _pending_api_call_timer for {self.entity_id}. "
                    f"Expected a callable, got {type(self._pending_api_call_timer)}. Value: {self._pending_api_call_timer}."
                )

        _LOGGER.debug(
            f"Scheduling _process_debounced_value for {self.entity_id} (Gen: {local_generation_for_job}, Value: {value})."
        )

        job_target = functools.partial(
            self._process_debounced_value, local_generation_for_job, value
        )

        new_timer_handle = async_call_later(
            self.hass,
            NUMBER_SET_VALUE_DEBOUNCE_DELAY_S,
            HassJob(
                job_target,
                name=f"HdgBoilerNumber_DebounceProcess_{self.entity_id}_{value}_{local_generation_for_job}",
                cancel_on_shutdown=True,
            ),
        )
        self._pending_api_call_timer = new_timer_handle

    async def _process_debounced_value(self, *args: Any) -> None:
        """
        Process the debounced value and queue it for an API call via the coordinator.

        This method is scheduled by `async_set_native_value` and executed after
        the `NUMBER_SET_VALUE_DEBOUNCE_DELAY_S`. It checks if the job's generation
        matches the current generation to ensure only the most recent value
        set by the user is processed.

        Args:
            *args: A tuple containing (scheduled_generation: int, value_at_schedule_time: float).
                   `scheduled_generation` is the generation number when this job was scheduled.
                   `value_at_schedule_time` is the value that was intended to be set.
        """
        if len(args) < 2:
            _LOGGER.error(
                f"{self.entity_id}: _process_debounced_value called with insufficient arguments: {args}"
            )
            return

        scheduled_generation: int = args[0]
        value_at_schedule_time: float = args[1]

        _LOGGER.debug(
            f"_process_debounced_value START for {self.entity_id}: "
            f"Scheduled Gen={scheduled_generation} (Value: {value_at_schedule_time}), "
            f"Current Instance Gen={self._current_set_generation} (Current Instance Value: {self._value_for_current_generation})"
        )

        # This check ensures that if multiple set_value calls were made quickly,
        # only the one for the latest generation proceeds.
        if scheduled_generation != self._current_set_generation:
            _LOGGER.debug(
                f"{self.entity_id}: Job for generation {scheduled_generation} (value: {value_at_schedule_time}) is stale. "
                f"Current generation is {self._current_set_generation} (value: {self._value_for_current_generation}). Skipping API call."
            )
            return

        value_to_process = value_at_schedule_time
        setter_type = cast(
            str, self._entity_definition.get("setter_type")
        )  # Assumed to be valid by this point.

        try:
            _LOGGER.debug(
                f"{self.entity_id}: Job for generation {scheduled_generation} (value: {value_to_process}) IS CURRENT. Proceeding to queue for API."
            )

            api_value_to_send_str = format_value_for_api(value_to_process, setter_type)

            # Delegate the actual API call to the coordinator's queue.
            success = await self.coordinator.async_set_node_value_if_changed(
                node_id=self._node_id,
                new_value_str_for_api=api_value_to_send_str,
                entity_name_for_log=self.name or self.entity_id,
            )
            if not success:
                _LOGGER.error(
                    f"Failed to queue/set value for {self.name or self.entity_id} (coordinator reported unchanged or queue full) for value {value_to_process}."
                )
            else:
                _LOGGER.info(
                    f"Successfully queued set request for {self.name or self.entity_id} to {value_to_process} (API value: {api_value_to_send_str})."
                )
        except ValueError as err:  # From format_value_for_api, indicates config issue.
            _LOGGER.error(
                f"Configuration error for {self.entity_id} preventing value set. "
                f"Details: {err}. Please check SENSOR_DEFINITIONS."
            )
        except HdgApiError as err:  # From coordinator if API call within worker fails.
            _LOGGER.error(
                f"API error during coordinator.async_set_node_value_if_changed for {self.entity_id} with value {value_to_process}: {err}"
            )
        except Exception as err:  # Catch-all for other unexpected issues.
            _LOGGER.exception(
                f"Unexpected error during processing/queueing of debounced value for {self.entity_id} with value {value_to_process}: {err}"
            )

    async def async_will_remove_from_hass(self) -> None:
        """
        Handle entity being removed from Home Assistant.

        Ensures that any pending debounced API call timer is cancelled.
        """
        if self._pending_api_call_timer:
            if callable(self._pending_api_call_timer):
                self._pending_api_call_timer()  # Call the cancel callback
            self._pending_api_call_timer = None
            _LOGGER.debug(
                f"Cancelled API call timer for {self.entity_id} during removal."
            )
        await super().async_will_remove_from_hass()


def _determine_ha_number_step_val(
    entity_def: SensorDefinition,
    translation_key: str,  # Used for logging context.
    raw_hdg_node_id: str,  # Used for logging context.
) -> float | None:
    """
    Determine the `native_step` for the Home Assistant NumberEntity.

    This function interprets the 'setter_step' from the entity definition.
    If 'setter_step' is not defined, it infers a default step (0.1 for floats,
    1.0 for integers). If 'setter_step' is 0.0, it logs a warning and uses
    a default UI step, as HA requires a positive step for UI controls; the
    actual 0.0 step logic (meaning only `min_value` is allowed) is enforced
    during service call validation.

    Returns:
        The step value as a float if valid.
        None if a critical configuration error is found (e.g., invalid or negative step),
        which should prevent entity creation.
    """
    setter_type_for_step_default = (entity_def.get("setter_type") or "").strip().lower()
    raw_step_val_config = entity_def.get("setter_step")
    step_val: float

    if raw_step_val_config is None:
        # Infer default step based on setter_type if 'setter_step' is not explicitly defined
        step_val = 0.1 if setter_type_for_step_default in {"float1", "float2"} else 1.0
        _LOGGER.debug(
            f"'setter_step' not defined for translation_key '{translation_key}' (Node {raw_hdg_node_id}). "
            f"Detected setter_type '{setter_type_for_step_default}', defaulting HA NumberEntity step to {step_val}."
        )
        return step_val

    # At this point, raw_step_val_config is not None.
    try:
        parsed_step_val_config = float(raw_step_val_config)
    except (ValueError, TypeError):
        _LOGGER.error(
            f"Invalid 'setter_step' value '{raw_step_val_config}' in SENSOR_DEFINITIONS for translation_key '{translation_key}' (Node {raw_hdg_node_id}). "
            f"Must be a number. This entity will be skipped."
        )
        return None  # Indicates a critical error, entity should not be created.

    if parsed_step_val_config < 0.0:
        _LOGGER.error(
            f"Invalid 'setter_step' value {parsed_step_val_config} (negative) in SENSOR_DEFINITIONS for translation_key '{translation_key}' (Node {raw_hdg_node_id}). "
            f"Step must be non-negative. This entity will be skipped."
        )
        return None  # Critical error.
    elif parsed_step_val_config == 0.0:
        # Home Assistant UI requires a positive step for number entities.
        # The actual logic for a 0.0 step (meaning only min_value is allowed)
        # is enforced during the service call validation in services.py.
        step_val = 0.1 if setter_type_for_step_default in {"float1", "float2"} else 1.0
        _LOGGER.warning(
            f"[{translation_key}][{raw_hdg_node_id}] SENSOR_DEFINITIONS has 'setter_step' of 0.0. "
            f"Only 'setter_min_val' is valid for API calls. HA UI will use step {step_val}, potentially confusing users. "
            "Service calls will correctly enforce the 0.0 step logic (only min_value allowed)."
        )
        return step_val
    return parsed_step_val_config  # Valid, positive step defined.


def _create_number_entity_if_valid(
    translation_key: str,
    entity_def: SensorDefinition,
    coordinator: HdgDataUpdateCoordinator,
    api_client: HdgApiClient,
) -> HdgBoilerNumber | None:
    """
    Validate an entity definition and create an HdgBoilerNumber entity.

    This function checks for the presence and validity of essential keys in the
    entity definition: 'hdg_node_id', 'setter_type', 'setter_min_val', and
    'setter_max_val'. It also determines the appropriate step value for the
    Home Assistant NumberEntity using `_determine_ha_number_step_val`.
    If any validation fails, None is returned, and the entity is not created.

    Returns:
        An HdgBoilerNumber entity instance if the definition is valid, otherwise None.
    """
    hdg_node_id_with_suffix = entity_def.get("hdg_node_id")
    if not isinstance(hdg_node_id_with_suffix, str) or not hdg_node_id_with_suffix:
        _LOGGER.warning(
            f"Skipping number entity for translation_key '{translation_key}': "
            f"missing or invalid 'hdg_node_id' (value: {hdg_node_id_with_suffix})."
        )
        return None
    raw_hdg_node_id = strip_hdg_node_suffix(
        hdg_node_id_with_suffix
    )  # Base ID for API calls.

    setter_type = entity_def.get("setter_type")
    if not isinstance(setter_type, str) or not setter_type:
        _LOGGER.warning(
            f"Skipping number entity for translation_key '{translation_key}' (HDG Node {raw_hdg_node_id}): "
            f"Missing or invalid 'setter_type' (value: {setter_type})."
        )
        return None

    min_val_def = entity_def.get("setter_min_val")
    max_val_def = entity_def.get("setter_max_val")
    try:
        # Cast to float as it's expected to be convertible by the caller (_create_number_entity_if_valid)
        min_val = float(
            cast(float, min_val_def)
        )  # Ensure min_val can be converted to float.
        max_val = float(
            cast(float, max_val_def)
        )  # Ensure max_val can be converted to float.
    except (ValueError, TypeError) as e:
        _LOGGER.error(
            f"Invalid 'setter_min_val' ('{min_val_def}') or 'setter_max_val' ('{max_val_def}') "
            f"in SENSOR_DEFINITIONS for '{translation_key}' (Node {raw_hdg_node_id}): {e}. "
            "Values must be numbers. This entity will be skipped."
        )
        return None

    ha_native_step_val = _determine_ha_number_step_val(
        entity_def, translation_key, raw_hdg_node_id
    )
    if ha_native_step_val is None:
        # Error already logged by _determine_ha_number_step_val.
        return None

    description = NumberEntityDescription(
        key=translation_key,  # Used by HA for unique ID generation internally.
        name=None,  # HA derives name from translation_key.
        translation_key=translation_key,  # For localization.
        icon=entity_def.get("icon"),
        device_class=entity_def.get("ha_device_class"),
        native_unit_of_measurement=entity_def.get("ha_native_unit_of_measurement"),
        entity_category=entity_def.get("entity_category"),
        native_min_value=min_val,
        native_max_value=max_val,
        native_step=ha_native_step_val,
        mode=NumberMode.BOX,  # UI presentation style.
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

    Iterates through SENSOR_DEFINITIONS, creating number entities for those
    defined with `ha_platform: "number"` and having valid setter parameters.
    """
    integration_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HdgDataUpdateCoordinator = integration_data["coordinator"]
    api_client: HdgApiClient = integration_data["api_client"]

    number_entities: list[HdgBoilerNumber] = []

    for translation_key, entity_definition_dict in SENSOR_DEFINITIONS.items():
        entity_def = cast(SensorDefinition, entity_definition_dict)

        if entity_def.get("ha_platform") == "number":
            # Validate and create the entity if the definition is suitable.
            if entity := _create_number_entity_if_valid(
                translation_key, entity_def, coordinator, api_client
            ):
                number_entities.append(entity)

    if number_entities:
        async_add_entities(number_entities)
        _LOGGER.info(f"Added {len(number_entities)} HDG Bavaria number entities.")
    else:
        _LOGGER.info(
            "No number entities to add. Check SENSOR_DEFINITIONS for 'number' platform entities "
            "with valid setter parameters."
        )
