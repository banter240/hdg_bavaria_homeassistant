"""
Sensor platform for the HDG Bavaria Boiler integration.

This module sets up sensor entities that display various data points
read from the HDG Bavaria boiler system.
"""

from __future__ import annotations

__version__ = "0.7.0"

import logging
import re
from datetime import datetime
from typing import Any, Optional, cast

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util  # Date/time utilities for timezone conversions.

from .const import (
    DOMAIN,
    SENSOR_DEFINITIONS,
    SensorDefinition,  # TypedDict for items in SENSOR_DEFINITIONS
)
from .coordinator import HdgDataUpdateCoordinator
from .entity import HdgNodeEntity  # Base class for entities linked to HDG nodes

_LOGGER = logging.getLogger(DOMAIN)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HDG Bavaria sensor entities based on a config entry."""
    # Retrieve the coordinator from hass.data. The coordinator is responsible for
    # fetching data from the HDG boiler and was populated during the integration's initial setup in __init__.py.
    coordinator: HdgDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[HdgBoilerSensor] = []

    # Iterate through all predefined sensor/entity definitions.
    for unique_id_suffix, entity_definition_dict in SENSOR_DEFINITIONS.items():
        entity_def = cast(SensorDefinition, entity_definition_dict)

        # Only create sensor entities for those definitions explicitly marked for the "sensor" platform
        # in the SENSOR_DEFINITIONS constant.
        if entity_def.get("ha_platform") == "sensor":
            # Create a standard Home Assistant SensorEntityDescription.
            # This description is used by the SensorEntity base class and helps define
            # how the entity appears and behaves in Home Assistant.
            # Setting 'name=None' and providing a 'translation_key' allows Home Assistant to handle entity naming and localization.
            description = SensorEntityDescription(
                key=unique_id_suffix,  # This key is used for internal HA identification.
                name=None,  # Entity name will be derived from translation_key by Home Assistant.
                icon=entity_def.get("icon"),
                device_class=entity_def.get("ha_device_class"),
                native_unit_of_measurement=entity_def.get("ha_native_unit_of_measurement"),
                state_class=entity_def.get("ha_state_class"),
                entity_category=entity_def.get("entity_category"),
                translation_key=entity_def.get(
                    "translation_key"
                ),  # Enables localized entity names via translations.json.
            )
            # The HdgNodeEntity base class (and its parent HdgBaseEntity) handles common
            # setup tasks such as unique ID generation and device info assignment,
            # utilizing the comprehensive entity_def.
            entities.append(HdgBoilerSensor(coordinator, description, entity_def))
            _LOGGER.debug(
                f"Preparing HDG sensor for translation_key: {unique_id_suffix} "
                f"(HDG Node ID: {entity_def.get('hdg_node_id', 'N/A')})"
            )

    if entities:
        async_add_entities(entities)
        _LOGGER.info(f"Added {len(entities)} HDG Bavaria sensor entities.")
    else:
        _LOGGER.info("No sensor entities to add from SENSOR_DEFINITIONS.")


class HdgBoilerSensor(HdgNodeEntity, SensorEntity):
    """
    Representation of an HDG Bavaria Boiler sensor.

    This class inherits from HdgNodeEntity (for HDG-specific node logic)
    and SensorEntity (for Home Assistant sensor platform integration).
    """

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        entity_description: SensorEntityDescription,  # Standard HA entity description.
        entity_definition: SensorDefinition,  # Our comprehensive definition from const.py.
    ) -> None:
        """Initialize the sensor."""
        # HdgNodeEntity's __init__ handles setting up common attributes like unique_id,
        # device_info, and stores self._node_id (base HDG ID) and self._entity_definition.
        # It uses entity_definition["translation_key"] (via unique_id_suffix) for unique ID construction.
        # The base HDG node ID (without T/U/V/W/X/Y suffix) is extracted for data retrieval.
        super().__init__(
            coordinator, entity_definition["hdg_node_id"].rstrip("TUVWXY"), entity_definition
        )
        # Store the standard Home Assistant entity description. This is used by the SensorEntity
        # base class and provides attributes like device_class, unit_of_measurement, etc.
        # It also carries the translation_key for localized naming.
        self.entity_description = entity_description

        # _attr_has_entity_name is set to True in HdgBaseEntity.
        # Home Assistant uses self.entity_description.translation_key for naming
        # when self.entity_description.name is None and self.has_entity_name is True.
        _LOGGER.debug(
            f"HdgBoilerSensor {self.entity_description.key}: Initialized. "
            f"entity_description.name='{self.entity_description.name}', "
            f"entity_description.translation_key='{self.entity_description.translation_key}', "
            f"self.has_entity_name='{self.has_entity_name}'."
        )

        # Initialize the sensor's native value. This will be populated by _update_sensor_state
        # during the first coordinator update and subsequent updates.
        self._attr_native_value = None
        self._update_sensor_state()  # Perform an initial state update upon creation.

    @property
    def native_value(self) -> Any | None:
        """
        Return the state of the sensor.

        This property is managed by `_attr_native_value`, which is updated
        by `_handle_coordinator_update` via `_update_sensor_state`.
        """
        return self._attr_native_value

    @callback
    def _handle_coordinator_update(self) -> None:
        """
        Handle updated data from the coordinator.

        This method is called by the CoordinatorEntity base class when new data is available.
        It updates the sensor's state and then calls the superclass's method, which
        schedules an update for Home Assistant to write the new state.
        """
        self._update_sensor_state()
        super()._handle_coordinator_update()  # Schedules an update via async_write_ha_state.

    def _update_sensor_state(self) -> None:
        """Update the sensor's state based on the current data from the coordinator."""
        # Determine availability using HdgNodeEntity's logic, which checks both
        # the coordinator's overall status and the presence/validity of this specific node's data.
        self._attr_available = super().available

        if not self._attr_available:
            # Ensure the entity's state is explicitly set to None if it's considered unavailable.
            self._attr_native_value = None
            return

        # Retrieve the raw text value for this entity's node ID from the coordinator's data.
        # self._node_id (base HDG ID) is set by HdgNodeEntity.
        raw_value_text = self.coordinator.data.get(self._node_id)
        self._attr_native_value = self._parse_value(raw_value_text)

    def _parse_value(self, raw_value_text: Optional[str]) -> Any | None:
        """
        Parse the raw string value from the API into the correct type for the sensor's state.

        This method uses hints from the entity_definition (e.g., 'parse_as_type', 'hdg_formatter')
        to determine the appropriate parsing logic.
        """
        if raw_value_text is None:
            return None

        # Retrieve parsing hints from the entity_definition (stored in HdgNodeEntity's self._entity_definition).
        parse_as_type = self._entity_definition.get("parse_as_type")
        formatter = self._entity_definition.get("hdg_formatter")
        data_type = self._entity_definition.get("hdg_data_type")  # Original data type from HDG API.

        cleaned_value = raw_value_text.strip()

        # Availability checks for common "unavailable" markers like "---", "n/a", etc.,
        # are primarily handled by the `available` property of the HdgNodeEntity base class.
        # If `super().available` is True, `raw_value_text` should ideally not be one of these markers.
        # This parsing logic focuses on converting valid, available data.
        # However, an explicitly empty string might still need specific handling depending on 'parse_as_type'.
        if parse_as_type == "allow_empty_string" and cleaned_value == "":
            return ""  # Allow empty string as a valid state if specified.
        if cleaned_value == "":  # For most other types, an empty string implies no valid data.
            return None

        # Handle datetime parsing for timestamp sensors.
        if parse_as_type == "hdg_datetime_or_text":
            cleaned_value_dt = cleaned_value.replace("&nbsp;", " ")  # Clean potential HTML space.
            # Handle a specific text value from the API (e.g., "größer 7 tage") that indicates
            # an invalid or placeholder future date, returning it as text.
            if "größer 7 tage" in cleaned_value_dt.lower():  # "greater than 7 days"
                return cleaned_value_dt  # Return the text as-is for this special case.
            try:
                # Parse the datetime string, assuming a specific local format from the API.
                dt_object_naive = datetime.strptime(cleaned_value_dt, "%d.%m.%Y %H:%M")
                # Convert the naive datetime to a timezone-aware local datetime.
                dt_object_local_aware = dt_util.as_local(dt_object_naive)
                # Convert to UTC for internal Home Assistant storage.
                return dt_util.as_utc(dt_object_local_aware)
            except ValueError:
                _LOGGER.debug(
                    f"Node {self._node_id}: Could not parse '{cleaned_value_dt}' as datetime. Setting to None."
                )
                return None  # Return None if datetime parsing fails.

        # Handle parsing for percentage values from specific string formats.
        elif parse_as_type == "percent_from_string_regex":
            match = re.search(r"(\d+)\s*%-Schritte", cleaned_value)  # e.g., "10 %-Schritte"
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    _LOGGER.warning(
                        f"Node {self._node_id}: Could not parse numeric part from '{cleaned_value}' for percent_from_string_regex."
                    )
                    return None
            _LOGGER.debug(
                f"Node {self._node_id}: Regex did not find percentage in '{cleaned_value}' for percent_from_string_regex."
            )
            return None  # Regex did not match.

        # Handle enum text values.
        elif (
            parse_as_type == "enum_text" or data_type == "10"
        ):  # HDG data_type "10" often indicates an enumeration.
            # This returns the direct text from the API. For more structured enum handling,
            # one might map these to standardized keys using HDG_ENUM_MAPPINGS (defined in const.py).
            return cleaned_value

        # Handle general float parsing, typically for HDG data_type "2".
        elif parse_as_type == "float" or (
            data_type == "2"
            and formatter not in ["iVERSION", "iREVISION"]  # Exclude version strings.
        ):
            try:
                cleaned_numeric_string = cleaned_value.replace(
                    ",", "."
                )  # Normalize decimal separator.
                match = re.search(
                    r"([-+]?\d*\.?\d+)", cleaned_numeric_string
                )  # Extract numeric part.
                if match:
                    val_float = float(match.group(1))
                    # Apply specific rounding for "iFLOAT2" formatter.
                    if formatter == "iFLOAT2":
                        return round(val_float, 2)
                    # For certain formatters that typically represent whole numbers (e.g., kWh, hours, minutes, liters),
                    # return as an integer if the float value is indeed a whole number to avoid ".0" display.
                    # Otherwise, return as float.
                    if formatter in [
                        "iKWH",
                        "iMWH",
                        "iSTD",  # Hours
                        "iMIN",  # Minutes
                        "iSEK",  # Seconds
                        "iLITER",  # Liters
                    ] and val_float == int(val_float):
                        return int(val_float)
                    return val_float  # Default to float.
                else:
                    _LOGGER.debug(
                        f"No numeric part found in '{cleaned_value}' for sensor {self.entity_id} (formatter: {formatter})."
                    )
                    return None  # Return None if no numeric part is found.
            except ValueError:
                _LOGGER.warning(
                    f"Could not parse numeric value for {self.entity_id} from text: '{cleaned_value}' (formatter: {formatter})."
                )
                return None  # Parsing to float failed.

        # Handle explicit integer parsing.
        elif parse_as_type == "int":
            try:
                cleaned_numeric_string = cleaned_value.replace(",", ".")  # Normalize decimal.
                match = re.search(
                    r"([-+]?\d*\.?\d+)", cleaned_numeric_string
                )  # Extract numeric part.
                if match:
                    # Convert to float first to handle potential decimal inputs, then to int for truncation.
                    return int(float(match.group(1)))
                else:
                    _LOGGER.debug(
                        f"No numeric part found in '{cleaned_value}' for int sensor {self.entity_id}."
                    )
                    return None  # Return None if no numeric part is found.
            except ValueError:
                _LOGGER.warning(
                    f"Could not parse int value for {self.entity_id} from text: '{cleaned_value}'."
                )
                return None  # Return None if parsing to int fails.

        # Handle plain text values, including version strings.
        elif parse_as_type == "text" or data_type == "4" or formatter in ["iVERSION", "iREVISION"]:
            return cleaned_value

        # Fallback for unhandled parsing scenarios. This log helps identify if new data types
        # or formatters appear from the API that are not yet explicitly handled.
        _LOGGER.warning(
            f"Unhandled value parsing for {self.entity_id}. Raw: '{raw_value_text}', "
            f"ParseAs: {parse_as_type}, HDG Type: {data_type}, Formatter: {formatter}"
        )
        return None  # Default to None if no specific parsing rule matched.
