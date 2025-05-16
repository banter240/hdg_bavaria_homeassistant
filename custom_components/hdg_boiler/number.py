"""
Platform for number entities for the HDG Bavaria Boiler integration.

This module sets up number entities that allow users to view and control
numeric settings on their HDG Bavaria boiler system.
"""

__version__ = "0.7.0"

import logging
import re
from typing import Any, Dict, Optional, cast
import asyncio

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, HassJob
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    SENSOR_DEFINITIONS,
    NUMBER_SET_VALUE_DEBOUNCE_DELAY_S,  # Debounce delay for setting values
    SensorDefinition,  # TypedDict for SENSOR_DEFINITIONS items
)
from .coordinator import HdgDataUpdateCoordinator
from .entity import HdgNodeEntity
from .api import (
    HdgApiClient,  # HdgApiClient is passed to the entity constructor.
    HdgApiError,
)

_LOGGER = logging.getLogger(DOMAIN)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HDG number entities from a config entry."""
    # Retrieve the coordinator and API client from hass.data.
    # These are populated during the initial setup of the integration in __init__.py.
    integration_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HdgDataUpdateCoordinator = integration_data["coordinator"]
    # The api_client is passed to the entity constructor. While current value setting
    # is debounced and routed via the coordinator's `async_set_node_value_if_changed` method,
    # having the api_client instance available in the entity could be useful for
    # future enhancements or more direct interactions if necessary, though not currently used
    # for setting values from the HdgBoilerNumber entity itself.
    api_client: HdgApiClient = integration_data["api_client"]

    number_entities: list[HdgBoilerNumber] = []

    # Iterate through all defined sensors/entities to find those configured as "number" platforms.
    for translation_key, entity_definition_dict in SENSOR_DEFINITIONS.items():
        entity_def = cast(SensorDefinition, entity_definition_dict)

        if entity_def.get("ha_platform") != "number":
            continue  # Only process definitions intended for the 'number' platform.

        hdg_node_id_with_suffix = entity_def.get("hdg_node_id")
        if not hdg_node_id_with_suffix:
            _LOGGER.warning(
                f"Skipping number entity for translation_key '{translation_key}': "
                # This entity definition is missing the crucial 'hdg_node_id' which links it
                # to a specific data point on the HDG boiler.
                f"missing 'hdg_node_id' in SENSOR_DEFINITIONS."
            )
            continue

        # Extract the base HDG node ID (without T/U/V/W/X/Y suffix).
        # This base ID is used for data retrieval from the coordinator and for API set calls.
        raw_hdg_node_id = hdg_node_id_with_suffix.rstrip("TUVWXY")

        # Check if essential setter parameters are defined directly in the SensorDefinition.
        # 'setter_type' is used as a key indicator for the presence of setter configuration.
        if not entity_def.get("setter_type"):
            _LOGGER.warning(
                # This entity is defined as a 'number' platform but lacks the necessary
                # 'setter_type' (and likely other 'setter_*') parameters in its SENSOR_DEFINITION.
                f"Skipping number entity for translation_key '{translation_key}' (HDG Node {raw_hdg_node_id}): "
                f"Missing 'setter_type' or other required setter parameters (setter_min_val, setter_max_val, setter_step) "
                f"in SENSOR_DEFINITIONS."
            )
            continue

        # Prepare NumberEntityDescription using data from SENSOR_DEFINITIONS.
        # Default values (0.0, 100.0, 1.0) are used for min/max/step if not explicitly defined
        # in the entity_def, ensuring the NumberEntityDescription has valid numeric bounds.
        min_val = float(entity_def.get("setter_min_val", 0.0))
        max_val = float(entity_def.get("setter_max_val", 100.0))
        step_val_config = entity_def.get("setter_step", 1.0)

        # Ensure step is not zero, as HA number entities require a non-zero step.
        # If the configured step from SENSOR_DEFINITIONS is 0 (which might be an API/device quirk
        # indicating a fixed value or specific behavior), provide a sensible fallback for HA:
        # 0.1 for 'float' setter types, 1.0 for 'int' or other types.
        setter_type_for_step_check = entity_def.get("setter_type", "").lower()
        step_val = (
            float(step_val_config)
            if float(step_val_config) != 0.0
            else (0.1 if "float" in setter_type_for_step_check else 1.0)
        )

        # Create the Home Assistant standard NumberEntityDescription.
        # This defines how the number entity behaves and appears in the HA UI.
        description = NumberEntityDescription(
            key=translation_key,  # This key is unique for each HA entity.
            name=None,  # Entity name will be derived from translation_key by Home Assistant.
            translation_key=translation_key,  # Enables localized entity names.
            icon=entity_def.get("icon"),
            device_class=entity_def.get("ha_device_class"),
            native_unit_of_measurement=entity_def.get("ha_native_unit_of_measurement"),
            entity_category=entity_def.get("entity_category"),
            native_min_value=min_val,
            native_max_value=max_val,
            native_step=step_val,
            # Use BOX mode for direct input; slider might be too coarse for some step values
            # or value ranges encountered with boiler settings.
            mode=NumberMode.BOX,
        )

        number_entities.append(HdgBoilerNumber(coordinator, api_client, description, entity_def))
        _LOGGER.debug(
            f"Preparing HDG number entity for translation_key: {translation_key} "
            f"(HDG Node for API set: {raw_hdg_node_id}, SENSOR_DEF Node ID: {hdg_node_id_with_suffix})"
        )

    if number_entities:
        async_add_entities(number_entities)
        _LOGGER.info(f"Added {len(number_entities)} HDG Bavaria number entities.")
    # This log message is useful if, for example, SENSOR_DEFINITIONS contains items intended
    # as 'number' entities but they are missing the required 'setter_type' configuration.
    else:
        _LOGGER.info(
            "No number entities to add from SENSOR_DEFINITIONS with required setter parameters."
        )


class HdgBoilerNumber(HdgNodeEntity, NumberEntity):
    """
    Representation of an HDG Boiler Number entity.

    This entity allows users to view and set numeric values on the HDG boiler.
    It relies on the HdgDataUpdateCoordinator for state updates and debounces API calls
    for setting values to prevent flooding the HDG device.
    """

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        api_client: HdgApiClient,
        entity_description: NumberEntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """Initialize the number entity."""
        # HdgNodeEntity's __init__ handles setting up common attributes like unique_id,
        # device_info, and stores self._node_id (base HDG ID) and self._entity_definition.
        # The base HDG node ID (without T/U/V/W/X/Y suffix) is extracted from entity_definition["hdg_node_id"]
        # and used for data retrieval and API set calls.
        hdg_api_node_id_from_def = entity_definition["hdg_node_id"]
        super().__init__(coordinator, hdg_api_node_id_from_def.rstrip("TUVWXY"), entity_definition)

        # Store the standard Home Assistant entity description.
        # This provides native_min_value, native_max_value, native_step, mode, etc.
        # to the NumberEntity base class.
        self.entity_description = entity_description

        # Store the API client instance. Although value setting is currently routed via the
        # coordinator's `async_set_node_value_if_changed` method (which uses its own API client instance),
        # retaining this `api_client` here could be useful for future direct API interactions from the entity if needed.
        self._api_client = api_client

        # Debouncing attributes for setting values to prevent API call flooding.
        self._pending_api_call_timer: Optional[asyncio.TimerHandle] = None
        self._pending_value_to_set: Optional[float] = None

        # Initialize the entity's state from coordinator data.
        # This will be populated by _update_number_state during this initialization.
        self._attr_native_value = None
        self._update_number_state()  # Perform an initial state update upon creation.

        _LOGGER.debug(
            f"HdgBoilerNumber {self.entity_description.key}: Initialized. "
            f"Node ID: {self._node_id}, Min: {self.native_min_value}, Max: {self.native_max_value}, Step: {self.native_step}"
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """
        Handle updated data from the coordinator.

        This method is called by the CoordinatorEntity base class when new data is available.
        It updates the number's state and then calls the superclass's method, which
        schedules an update for Home Assistant to write the new state.
        """
        self._update_number_state()
        super()._handle_coordinator_update()  # Schedules an update via async_write_ha_state.

    def _update_number_state(self) -> None:
        """Update the number's state based on the coordinator's current data."""
        # Determine availability based on HdgNodeEntity's logic (checks coordinator and specific node data).
        self._attr_available = super().available

        if not self._attr_available:
            # Ensure the entity's state is None if it's considered unavailable.
            self._attr_native_value = None
            return

        # Retrieve the raw text value for this entity's node ID from the coordinator.
        # self._node_id (base HDG ID) is set by HdgNodeEntity.
        raw_value_text = self.coordinator.data.get(self._node_id)
        self._attr_native_value = self._parse_value(raw_value_text)

    def _parse_value(self, raw_value_text: Optional[str]) -> Optional[float]:
        """
        Parse the raw string value from the API into a float for the number entity's state.

        Returns None if parsing fails or the input is None.
        This method is specific to number entities and aims to extract a float.
        """
        if raw_value_text is None:
            return None

        cleaned_value = raw_value_text.strip()
        # If the string is empty after stripping whitespace, it cannot be parsed as a number.
        if not cleaned_value:
            return None

        try:
            # If the value is already numeric (int/float), directly cast to float.
            if isinstance(raw_value_text, (int, float)):
                return float(raw_value_text)

            # For string values, attempt to extract the first valid numeric part.
            # This regex is designed to capture integers and floats, including those with signs,
            # from strings that might contain units or other non-numeric characters (e.g., "70 °C", "50.5 %").
            match = re.search(r"([-+]?\d*\.?\d+)", cleaned_value)
            if match:
                return float(match.group(1))

            # If no numeric part is found, the value is unparseable for a number entity.
            _LOGGER.debug(
                f"Could not extract numeric part for {self.entity_id} from: '{cleaned_value}'"
            )
            return None
        except ValueError:
            _LOGGER.warning(
                f"Could not parse number value for {self.entity_id} from text: '{cleaned_value}'"
            )
            return None

    async def async_set_native_value(self, value: float) -> None:
        """
        Update the current value.

        This method is called by Home Assistant when the user changes the number entity's value.
        It debounces the API call to prevent rapid, successive calls if the user adjusts the value quickly.
        """
        _LOGGER.debug(
            f"async_set_native_value called for {self.entity_id} with value {value}. "
            f"Debouncing for {NUMBER_SET_VALUE_DEBOUNCE_DELAY_S}s."
        )

        self._pending_value_to_set = value

        # Cancel any existing timer to ensure only the latest value is sent.
        if self._pending_api_call_timer:
            self._pending_api_call_timer()  # Call the cancel function directly
            _LOGGER.debug(f"Cancelled existing API call timer for {self.entity_id}.")

        # Schedule the actual API call after the debounce delay.
        # Using HassJob ensures the callback (_execute_set_value_api_call)
        # runs within the Home Assistant event loop context.
        self._pending_api_call_timer = async_call_later(
            self.hass,
            NUMBER_SET_VALUE_DEBOUNCE_DELAY_S,
            HassJob(
                self._execute_set_value_api_call, name=f"HdgBoilerNumber_SetValue_{self.entity_id}"
            ),
        )

    async def _execute_set_value_api_call(self, *args: Any) -> None:
        """
        Execute the actual API call to set the node value after the debounce period.

        This method formats the value according to the node's 'setter_type' (defined in SENSOR_DEFINITIONS)
        and calls the coordinator to perform the API interaction.
        """
        if self._pending_value_to_set is None:
            # This might happen if the timer was somehow triggered without a pending value.
            _LOGGER.debug(f"No pending value to set for {self.entity_id}. Skipping API call.")
            return

        value_to_send_numeric = self._pending_value_to_set
        # Log at INFO level for actual API call initiation for better operational traceability.
        _LOGGER.info(
            f"Executing debounced API call for {self.entity_id} (Node ID: {self._node_id}) with value {value_to_send_numeric}"
        )

        # Retrieve the expected API data type from the entity definition.
        node_type = self._entity_definition.get("setter_type")
        api_value_to_send_str: str

        # Format the numeric value into the string representation expected by the HDG API.
        if node_type == "int":
            api_value_to_send_str = str(int(round(value_to_send_numeric)))
        elif node_type == "float1":
            # Format to one decimal place, ensuring dot as decimal separator for API.
            api_value_to_send_str = f"{value_to_send_numeric:.1f}".replace(",", ".")
        elif node_type == "float2":
            # Format to two decimal places, ensuring dot as decimal separator for API.
            api_value_to_send_str = f"{value_to_send_numeric:.2f}".replace(",", ".")
        else:  # Default to string representation if type is unknown or generic float.
            api_value_to_send_str = str(value_to_send_numeric)

        try:
            # Delegate the API call to the coordinator. The coordinator's method
            # handles the "if_changed" logic and updates its internal state, which then
            # triggers updates for all listening entities.
            # self._node_id is the base HDG ID (e.g., "6022") used for the API call.
            success = await self.coordinator.async_set_node_value_if_changed(
                node_id=self._node_id,
                new_value_to_set=api_value_to_send_str,
                entity_name_for_log=self.name
                or self.entity_id,  # Use entity name for clearer logs.
            )
            if not success:
                # The coordinator method logs details of API failures.
                # Raise a HomeAssistantError here to inform Home Assistant that the set operation
                # ultimately failed, allowing the UI to reflect this.
                _LOGGER.error(
                    f"Failed to set value for {self.name or self.entity_id} (API call reported failure by coordinator)."
                )
                raise HomeAssistantError(
                    f"Failed to set value for {self.name or self.entity_id} (API call reported failure by coordinator)."
                )
            # If successful, the coordinator will update its data, and _handle_coordinator_update
            # (called via super()._handle_coordinator_update()) will eventually refresh this
            # entity's state (self._attr_native_value) from the coordinator.
        except HdgApiError as err:
            _LOGGER.error(f"API error setting value for {self.entity_id}: {err}")
            raise HomeAssistantError(
                f"API error setting value for {self.name or self.entity_id}: {err}"
            ) from err
        except Exception as err:  # Catch any other unexpected errors.
            _LOGGER.exception(f"Unexpected error setting value for {self.entity_id}: {err}")
            raise HomeAssistantError(
                f"Unexpected error setting value for {self.name or self.entity_id}: {err}"
            ) from err
        finally:
            # Clear the pending state after the API call attempt.
            self._pending_api_call_timer = None
            self._pending_value_to_set = None
