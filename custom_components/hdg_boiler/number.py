"""
Provides number entities for the HDG Bavaria Boiler integration.

This module is responsible for creating and managing 'number' entities that
allow users to view and modify numeric settings on their HDG Bavaria boiler.
It handles state updates from the data coordinator and implements debouncing for API calls.
"""

from __future__ import annotations

__version__ = "0.8.68"

import functools
import logging
import time  # Import time for monotonic
from datetime import datetime
from typing import Any, cast

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .api import HdgApiClient
from .const import (
    DOMAIN,
    NUMBER_SET_VALUE_DEBOUNCE_DELAY_S,
    RECENTLY_SET_POLL_IGNORE_WINDOW_S,  # Import for use
)
from .coordinator import HdgDataUpdateCoordinator
from .definitions import SENSOR_DEFINITIONS
from .entity import HdgNodeEntity
from .exceptions import HdgApiError
from .helpers.parsing_utils import (
    format_value_for_api,
    parse_float_from_string,
)
from .helpers.string_utils import strip_hdg_node_suffix
from .helpers.validation_utils import (
    validate_value_range_and_step,
)
from .models import SensorDefinition

_LOGGER = logging.getLogger(DOMAIN)


class HdgBoilerNumber(HdgNodeEntity, NumberEntity):
    """
    Represents a number entity for an HDG Bavaria Boiler.

    This entity allows users to interact with numeric settings of the boiler,
    such as temperature setpoints. It handles optimistic UI updates, debounces
    API calls to prevent flooding the device, and validates input values.
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
            api_client: The API client for HDG communication (currently unused here, inherited).
            entity_description: The entity description for this number entity.
            entity_definition: The sensor definition dictionary for this entity.
        """
        hdg_api_node_id_from_def = entity_definition["hdg_node_id"]
        super().__init__(
            coordinator=coordinator,
            node_id=strip_hdg_node_suffix(hdg_api_node_id_from_def),
            entity_definition=cast(dict[str, Any], entity_definition),
        )
        self.entity_description = entity_description
        self._current_set_generation: int = 0
        self._pending_api_call_timer: CALLBACK_TYPE | None = None
        self._value_for_current_generation: float | None = None
        self._attr_native_value: int | float | None = None
        self._update_number_state()
        if self.coordinator.enable_debug_logging:
            _LOGGER.debug(
                # Use entity_description.key as self.entity_id might not be fully available at this stage.
                f"HdgBoilerNumber {self.entity_description.key or self._node_id}: Initialized. "
                f"Node ID: {self._node_id}, Min: {self.native_min_value}, Max: {self.native_max_value}, Step: {self.native_step}"
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data updates from the coordinator."""
        # This method is called when the coordinator has new data.
        # It updates the entity's state and then calls the superclass's
        # _handle_coordinator_update, which in turn calls async_write_ha_state.
        if self.coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"HdgBoilerNumber {self.entity_id}: _handle_coordinator_update called."
            )
        self._update_number_state()
        super()._handle_coordinator_update()
        if self.coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"HdgBoilerNumber {self.entity_id}: _handle_coordinator_update finished. New native_value: {self._attr_native_value}"
            )

    def _update_number_state(self) -> None:
        """
        Update the entity's internal state from coordinator data.

        This method implements logic to mitigate UI bouncing when a value is
        set optimistically and a poll with an older value arrives.
        """
        self._attr_available = super().available
        if not self._attr_available:
            self._attr_native_value = None
            if self.coordinator.enable_debug_logging:
                _LOGGER.debug(
                    f"HdgBoilerNumber {self.entity_id}: Not available, native_value set to None."
                )
            return

        raw_value_text = self.coordinator.data.get(self._node_id)
        parsed_value = self._parse_value(raw_value_text)
        current_ui_value = (
            self._attr_native_value
        )  # Value currently displayed in the UI.

        if self.coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"HdgBoilerNumber {self.entity_id}: _update_number_state: Node ID: {self._node_id}. "
                f"Optimistic (gen): {self._value_for_current_generation}, Parsed (poll): {parsed_value}, "
                f"Current UI: {current_ui_value}, Raw Coord: '{raw_value_text}'"
            )

        last_set_time = self.coordinator._last_set_times.get(
            self._node_id, 0.0
        )  # Accessing protected member for specific logic
        time_since_last_set = time.monotonic() - last_set_time
        is_recently_set_by_api = (
            last_set_time > 0.0
            and time_since_last_set < RECENTLY_SET_POLL_IGNORE_WINDOW_S
        )

        if self._value_for_current_generation is not None:
            # An optimistic value is active (i.e., user just changed it in the UI).
            if parsed_value == self._value_for_current_generation:
                # Polled value matches the optimistic value.
                # This means the set operation was successful and confirmed by this poll.
                self._attr_native_value = parsed_value
                self._value_for_current_generation = (
                    None  # Clear optimistic state as it's confirmed by poll.
                )
                if self.coordinator.enable_debug_logging:
                    _LOGGER.debug(
                        f"HdgBoilerNumber {self.entity_id}: _update_number_state: BRANCH A (Optimistic matches Poll). "
                        f"UI updated to {parsed_value}. Optimistic state cleared."
                    )
            # Polled value differs from optimistic. Keep optimistic UI.
            # self._attr_native_value already holds the optimistic value set in
            # async_set_native_value, so no change is needed here.
            elif self.coordinator.enable_debug_logging:
                _LOGGER.debug(
                    f"HdgBoilerNumber {self.entity_id}: _update_number_state: BRANCH B (Optimistic differs from Poll). "
                    f"Keeping optimistic UI value {self._attr_native_value}. Polled was {parsed_value}."
                )
        elif is_recently_set_by_api:
            # No optimistic value active from UI, but API set this node recently.
            # The HdgPollingResponseProcessor should have already handled ignoring this poll
            # if the polled value differed from what the worker set.
            # If we reach here, it means the PollingResponseProcessor allowed this polled value.
            # This typically means the polled value matches what was set by the worker,
            # or the ignore window passed.
            # We trust the PollingResponseProcessor's decision and update from the poll.
            self._attr_native_value = parsed_value  # Update UI from the polled value.
            if self.coordinator.enable_debug_logging:
                _LOGGER.debug(
                    f"HdgBoilerNumber {self.entity_id}: _update_number_state: BRANCH C (No optimistic, but recently set by API). "
                    f"UI updated from poll to {parsed_value}. PollingResponseProcessor should have filtered if needed."
                )
        else:
            # No optimistic value, and not recently set by API. Standard update from poll.
            self._attr_native_value = parsed_value
            if self.coordinator.enable_debug_logging:
                _LOGGER.debug(
                    f"HdgBoilerNumber {self.entity_id}: _update_number_state: BRANCH D (Standard poll update). "
                    f"UI updated from poll to {parsed_value}."
                )

    def _parse_value(self, raw_value_text: str | None) -> int | float | None:
        """
        Parse the raw string value from the API into an int or float.

        Args:
            raw_value_text: The raw string value received from the API.

        Returns:
            The parsed numeric value (int or float), or None if parsing fails.
        """
        if raw_value_text is None:
            return None
        cleaned_value = raw_value_text.strip()
        if not cleaned_value:
            return None

        parsed_float = parse_float_from_string(
            cleaned_value, self._node_id, self.entity_id
        )
        if parsed_float is None:
            _LOGGER.warning(
                f"HdgBoilerNumber {self.entity_id}: Could not parse float for node {self._node_id} from raw value '{raw_value_text}'."
            )
            return None

        if (
            self.native_step is not None
            and self.native_step == int(self.native_step)
            and parsed_float == int(parsed_float)
        ):
            return int(parsed_float)
        return parsed_float

    async def async_set_native_value(self, value: float) -> None:
        """
        Set the new native value and initiate a debounced API call.

        This method is called by Home Assistant when the user changes the value
        in the UI. It performs pre-validation, optimistically updates the UI,
        and schedules a debounced call to `_process_debounced_value` to
        handle the actual API communication.
        """
        if self.coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"HdgBoilerNumber {self.entity_id}: async_set_native_value called with UI value: {value} (type: {type(value)})"
            )

        # --- BEGIN Pre-validation ---
        try:
            min_val_def = self.native_min_value
            max_val_def = self.native_max_value
            node_step_def = self.native_step
            if (
                min_val_def is not None
                and max_val_def is not None
                and node_step_def is not None
            ):
                validate_value_range_and_step(
                    coerced_numeric_value=value,
                    min_val_def=min_val_def,
                    max_val_def=max_val_def,
                    node_step_def=node_step_def,
                    entity_name_for_log=self.name
                    if isinstance(self.name, str)
                    else self.entity_id,
                    node_id_str_for_log=self._node_id,
                    original_value_to_set_for_log=value,
                )
        except HomeAssistantError as e:
            _LOGGER.error(
                f"HdgBoilerNumber {self.entity_id}: Pre-validation failed for value {value}: {e}. Not setting value."
            )
            # Do not proceed with optimistic update or API call if validation fails.
            # UI should retain its previous valid state.
            return
        # --- END Pre-validation ---

        self._current_set_generation += 1
        local_generation_for_job = self._current_set_generation
        self._value_for_current_generation = (
            value  # Store the value for optimistic state tracking.
        )

        self._attr_native_value = (
            int(value)
            if self.native_step is not None
            and self.native_step == int(self.native_step)
            and value == int(value)
            else value
        )
        self.async_write_ha_state()
        if self.coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"HdgBoilerNumber {self.entity_id}: Optimistically set native_value to {self._attr_native_value}. Generation: {local_generation_for_job}."
            )

        if self._pending_api_call_timer:
            self._pending_api_call_timer()
            self._pending_api_call_timer = None

        if self.coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"HdgBoilerNumber {self.entity_id}: Scheduling _process_debounced_value (Gen: {local_generation_for_job}, UI Value: {value})."
            )
        job_target = functools.partial(
            self._process_debounced_value,
            scheduled_generation=local_generation_for_job,
            value_from_ui_at_schedule_time=value,
        )
        self._pending_api_call_timer = async_call_later(
            self.hass,
            NUMBER_SET_VALUE_DEBOUNCE_DELAY_S,
            HassJob(
                job_target,
                name=f"HdgNumDebounce_{self.entity_id}",
                cancel_on_shutdown=True,
            ),  # type: ignore
        )

    async def _process_debounced_value(  # sourcery skip: extract-method
        self,
        _now: datetime,
        scheduled_generation: int,
        value_from_ui_at_schedule_time: float,
    ) -> None:
        """
        Process the debounced value and queue it for an API call.

        This method is called by the timer set in `async_set_native_value`.
        It checks if the job is stale (i.e., if a newer value has been set in the meantime).
        If not stale, it formats the value for the API and queues it with the coordinator.
        Error handling is performed, and the optimistic state (`_value_for_current_generation`)
        is managed based on the outcome.
        """
        # _now parameter is provided by async_call_later, but not directly used here.
        if self.coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"HdgBoilerNumber {self.entity_id}: _process_debounced_value START. "
                f"Scheduled Gen={scheduled_generation}, UI Value={value_from_ui_at_schedule_time}, "
                f"Current Gen={self._current_set_generation}, OptimisticVal={self._value_for_current_generation}"
            )

        if self._is_job_stale(scheduled_generation):
            # If stale, but this was the generation that set the optimistic value, clear it.
            # This ensures that if the UI was showing an optimistic value from this stale job,
            # it can revert to a polled value.
            if (
                self._value_for_current_generation == value_from_ui_at_schedule_time
            ):  # Check if this job was the one that set the current optimistic value
                self._value_for_current_generation = None
                _LOGGER.warning(
                    f"HdgBoilerNumber {self.entity_id}: Stale job for {value_from_ui_at_schedule_time} was current optimistic. Cleared optimistic state."
                )
            return

        api_value_str: str | None = None
        try:
            api_value_str = self._format_value_for_api_safely(
                value_from_ui_at_schedule_time
            )
            await self._queue_set_value_via_coordinator(api_value_str)
        except Exception as err:
            self._handle_set_value_error(
                err, value_from_ui_at_schedule_time, api_value_str
            )
            # If API call failed, we should clear the optimistic state for this generation
            # to allow the next poll to reflect the actual (old) state.
            if (
                scheduled_generation == self._current_set_generation
                and self._value_for_current_generation == value_from_ui_at_schedule_time
            ):
                self._value_for_current_generation = (
                    None  # Clear optimistic state on error.
                )
                _LOGGER.warning(
                    f"HdgBoilerNumber {self.entity_id}: Cleared optimistic state for "
                    f"{value_from_ui_at_schedule_time} due to error in _process_debounced_value."
                )
        # Do NOT clear self._value_for_current_generation here unconditionally.
        # It should only be cleared if:
        # 1. The job was stale and it was the one that set the optimistic value. (Handled in _is_job_stale block)
        # 2. An error occurred during processing this specific generation. (Handled in except block)
        # 3. The value is successfully confirmed by a poll in _update_number_state (BRANCH A).

    def _is_job_stale(self, scheduled_generation: int) -> bool:
        """
        Check if the scheduled job for setting a value is stale.

        A job is considered stale if its generation number does not match the
        current set generation for this entity. This indicates that a newer
        value has been set by the user in the meantime.
        """
        if scheduled_generation != self._current_set_generation:
            _LOGGER.warning(
                f"HdgBoilerNumber {self.entity_id}: Job for gen {scheduled_generation} is STALE (current: {self._current_set_generation}). Skipping."
            )
            return True
        return False

    def _format_value_for_api_safely(self, value: float) -> str:
        """
        Format the numeric value into a string suitable for the HDG API.
        """
        setter_type = cast(str | None, self._entity_definition.get("setter_type"))
        if not setter_type:
            msg = f"HdgBoilerNumber {self.entity_id}: Missing 'setter_type'."
            _LOGGER.error(msg)
            raise ValueError(msg)
        return format_value_for_api(value, setter_type)

    async def _queue_set_value_via_coordinator(self, api_value_str: str) -> bool:
        """
        Queue the formatted value with the HdgDataUpdateCoordinator.

        The coordinator manages a worker task that handles the actual API call,
        including retries and API lock management.
        """
        if self.coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"HdgBoilerNumber {self.entity_id}: Queuing API value: '{api_value_str}'."
            )
        success = await self.coordinator.async_set_node_value_if_changed(
            node_id=self._node_id,
            # Pass entity_name_for_log to the coordinator method for its logging.
            new_value_str_for_api=api_value_str,
            entity_name_for_log=self.name
            if isinstance(self.name, str)
            else self.entity_id,
        )
        if not success:
            _LOGGER.error(
                f"HdgBoilerNumber {self.entity_id}: Failed to queue API value: '{api_value_str}'."
            )
        elif self.coordinator.enable_debug_logging:  # Only log success if debug is on
            _LOGGER.debug(
                f"HdgBoilerNumber {self.entity_id}: Successfully queued API value: '{api_value_str}'."
            )
        return bool(success)  # Return boolean success status.

    def _handle_set_value_error(
        self, err: Exception, value_to_process: float, api_value_str: str | None
    ) -> None:
        """
        Centralized error logging for the set value process.

        This method logs errors that occur during the formatting or queuing
        of a value to be set via the API.
        """
        if isinstance(err, ValueError):  # Config error
            _LOGGER.error(
                f"HdgBoilerNumber {self.entity_id}: Config error formatting UI value {value_to_process}: {err}."
            )
        elif isinstance(err, HdgApiError):  # API error from coordinator/worker
            _LOGGER.error(
                f"HdgBoilerNumber {self.entity_id}: API error for UI value {value_to_process} (API val: '{api_value_str}'): {err}"
            )
        else:  # Unexpected
            _LOGGER.exception(
                f"HdgBoilerNumber {self.entity_id}: Unexpected error for UI value {value_to_process} (API val: '{api_value_str}'): {err}"
            )

    async def async_will_remove_from_hass(self) -> None:
        """
        Handle entity being removed from Home Assistant.

        This method ensures that any pending API call timers are cancelled.
        """
        if self._pending_api_call_timer:
            self._pending_api_call_timer()
            self._pending_api_call_timer = None
        await super().async_will_remove_from_hass()


# (Rest of the file: _determine_ha_number_step_val, _create_number_entity_if_valid, async_setup_entry)
# These helper functions remain unchanged from version 0.8.60
# ... (Code from version 0.8.60 for these functions)
def _determine_ha_number_step_val(
    entity_def: SensorDefinition,
    translation_key: str,
    raw_hdg_node_id: str,
) -> float | None:
    """
    Determine the `native_step` for the Home Assistant NumberEntity.

    This function calculates the appropriate step value for the number entity's UI
    based on the 'setter_step' and 'setter_type' defined in the entity_definition.
    It provides default step values if 'setter_step' is not explicitly defined or
    if it's set to 0.0 (which has special meaning for the API but needs a
    sensible UI step).

    """
    setter_type_for_step_default = (entity_def.get("setter_type") or "").strip().lower()
    raw_step_val_config = entity_def.get("setter_step")
    step_val: float

    if raw_step_val_config is None:
        step_val = 0.1 if setter_type_for_step_default in {"float1", "float2"} else 1.0
        _LOGGER.debug(  # Unconditional debug in module-level helper
            f"'setter_step' not defined for translation_key '{translation_key}' (Node {raw_hdg_node_id}). "
            f"Detected setter_type '{setter_type_for_step_default}', defaulting HA NumberEntity step to {step_val}."
        )
        return step_val

    try:
        parsed_step_val_config = float(raw_step_val_config)
    except (ValueError, TypeError):
        _LOGGER.error(  # Keep as error
            f"Invalid 'setter_step' value '{raw_step_val_config}' in SENSOR_DEFINITIONS for translation_key '{translation_key}' (Node {raw_hdg_node_id}). "
            f"Must be a number. This entity will be skipped."
        )
        return None

    if parsed_step_val_config < 0.0:
        _LOGGER.error(  # Keep as error
            f"Invalid 'setter_step' value {parsed_step_val_config} (negative) in SENSOR_DEFINITIONS for translation_key '{translation_key}' (Node {raw_hdg_node_id}). "
            f"Step must be non-negative. This entity will be skipped."
        )
        return None
    if parsed_step_val_config == 0.0:
        step_val = 0.1 if setter_type_for_step_default in {"float1", "float2"} else 1.0
        _LOGGER.warning(  # Keep as warning
            f"[{translation_key}][{raw_hdg_node_id}] SENSOR_DEFINITIONS has 'setter_step' of 0.0. "
            f"Only 'setter_min_val' is valid for API calls. HA UI will use step {step_val}, potentially confusing users. "
            "Service calls will correctly enforce the 0.0 step logic (only min_value allowed)."
        )
        return step_val
    return parsed_step_val_config


def _create_number_entity_if_valid(
    translation_key: str,
    entity_def: SensorDefinition,
    coordinator: HdgDataUpdateCoordinator,
    api_client: HdgApiClient,
) -> HdgBoilerNumber | None:
    """
    Validate an entity definition and create an HdgBoilerNumber entity.

    This helper function checks if a given entity definition from `SENSOR_DEFINITIONS`
    is valid for creating an `HdgBoilerNumber` entity. It verifies the presence and
    correctness of required fields like `hdg_node_id`, `setter_type`, `setter_min_val`,
    `setter_max_val`, and calculates the `native_step`. If valid, it instantiates
    and returns an `HdgBoilerNumber` entity.
    """
    hdg_node_id_with_suffix = entity_def.get("hdg_node_id")
    if not isinstance(hdg_node_id_with_suffix, str) or not hdg_node_id_with_suffix:
        _LOGGER.warning(  # Keep as warning
            f"Skipping number entity for translation_key '{translation_key}': "
            f"missing or invalid 'hdg_node_id' (value: {hdg_node_id_with_suffix})."
        )
        return None
    raw_hdg_node_id = strip_hdg_node_suffix(hdg_node_id_with_suffix)

    setter_type = entity_def.get("setter_type")
    if not isinstance(setter_type, str) or not setter_type:
        _LOGGER.warning(  # Keep as warning
            f"Skipping number entity for translation_key '{translation_key}' (HDG Node {raw_hdg_node_id}): "
            f"Missing or invalid 'setter_type' (value: {setter_type})."
        )
        return None

    min_val_def = entity_def.get("setter_min_val")
    max_val_def = entity_def.get("setter_max_val")
    try:
        min_val = float(cast(float, min_val_def))
        max_val = float(cast(float, max_val_def))
    except (ValueError, TypeError) as e:
        _LOGGER.error(  # Keep as error
            f"Invalid 'setter_min_val' ('{min_val_def}') or 'setter_max_val' ('{max_val_def}') "
            f"in SENSOR_DEFINITIONS for '{translation_key}' (Node {raw_hdg_node_id}): {e}. "
            "Values must be numbers. This entity will be skipped."
        )
        return None

    ha_native_step_val = _determine_ha_number_step_val(
        entity_def, translation_key, raw_hdg_node_id
    )
    if ha_native_step_val is None:
        return None

    description = NumberEntityDescription(
        key=translation_key,
        name=None,
        translation_key=translation_key,
        icon=entity_def.get("icon"),  # type: ignore[arg-type]
        device_class=cast(NumberDeviceClass | None, entity_def.get("ha_device_class")),
        native_unit_of_measurement=entity_def.get("ha_native_unit_of_measurement"),
        entity_category=entity_def.get("entity_category"),
        native_min_value=min_val,
        native_max_value=max_val,
        native_step=ha_native_step_val,
        mode=NumberMode.BOX,
    )
    return HdgBoilerNumber(coordinator, api_client, description, entity_def)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Set up HDG Bavaria Boiler number entities from a config entry.

    This function is called by Home Assistant during the setup of the integration.
    It iterates through `SENSOR_DEFINITIONS`, identifies entities configured for
    the 'number' platform, validates their definitions, and creates
    `HdgBoilerNumber` instances for them.
    """
    integration_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HdgDataUpdateCoordinator = integration_data["coordinator"]
    api_client: HdgApiClient = integration_data["api_client"]
    number_entities: list[HdgBoilerNumber] = []

    for translation_key, entity_definition_dict in SENSOR_DEFINITIONS.items():
        entity_def = cast(SensorDefinition, entity_definition_dict)
        if entity_def.get("ha_platform") == "number":
            if entity := _create_number_entity_if_valid(
                translation_key, entity_def, coordinator, api_client
            ):
                number_entities.append(entity)

    if number_entities:
        async_add_entities(number_entities)
    _LOGGER.info(f"Added {len(number_entities)} HDG number entities.")  # Keep as info
