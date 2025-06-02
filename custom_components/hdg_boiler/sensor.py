"""
Sensor platform for the HDG Bavaria Boiler integration.

This module sets up sensor entities that display various data points
read from the HDG Bavaria boiler system.
"""

from __future__ import annotations

__version__ = "0.8.15"

import logging
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from datetime import datetime
from typing import Any, Optional, cast
from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from .const import (
    DOMAIN,
    CONF_SOURCE_TIMEZONE,
    DEFAULT_SOURCE_TIMEZONE,
    HDG_DATETIME_SPECIAL_TEXT,
)
from .definitions import (
    SENSOR_DEFINITIONS,
    SensorDefinition,
)
from .utils import (
    parse_percent_from_string,
    strip_hdg_node_suffix,
    parse_int_from_string,
    parse_float_from_string,
)
from .coordinator import HdgDataUpdateCoordinator
from .entity import HdgNodeEntity

_LOGGER = logging.getLogger(DOMAIN)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Set up HDG Bavaria sensor entities based on a configuration entry.

    This function iterates through SENSOR_DEFINITIONS, creating sensor entities
    for those marked for the 'sensor' platform. It uses the HdgDataUpdateCoordinator
    to provide data to these entities.
    """  # Retrieve the coordinator from hass.data; it's responsible for
    # fetching data from the HDG boiler and was populated during the integration's initial setup in __init__.py.
    coordinator: HdgDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[HdgBoilerSensor] = []

    for unique_id_suffix, entity_definition_dict in SENSOR_DEFINITIONS.items():
        entity_def = cast(SensorDefinition, entity_definition_dict)

        if entity_def.get("ha_platform") == "sensor":
            # Create a standard Home Assistant SensorEntityDescription.
            # This is used by SensorEntity and helps define appearance/behavior (per G-2.1.10.1).
            # Setting 'name=None' and providing a 'translation_key' allows Home Assistant
            # to handle entity naming and localization (per G-2.1.10.1).
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
            # HdgBoilerSensor inherits from HdgNodeEntity, which handles common setup
            # like unique ID generation and device info, using the entity_def.
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
    and SensorEntity (for Home Assistant sensor platform integration). It's responsible
    for parsing raw data from the coordinator into a displayable sensor state.
    """

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        entity_description: SensorEntityDescription,  # Standard HA entity description.
        entity_definition: SensorDefinition,  # Our comprehensive definition from const.py.
    ) -> None:
        """
        Initialize the sensor.

        Args:
            coordinator: The data update coordinator.
            entity_description: Standard Home Assistant entity description.
            entity_definition: Custom entity definition from SENSOR_DEFINITIONS.
        """
        # HdgNodeEntity's __init__ handles common setup:
        # - Sets up unique_id, device_info.
        # - Stores self._node_id (base HDG ID, suffix stripped) for data retrieval.
        # - Stores self._entity_definition.
        # - Uses entity_definition["translation_key"] for unique ID construction.
        hdg_api_node_id_from_def = entity_definition["hdg_node_id"]
        super().__init__(
            coordinator, strip_hdg_node_suffix(hdg_api_node_id_from_def), entity_definition
        )
        # Store the HA entity description, used by SensorEntity base class.
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
        # during the first coordinator update and on subsequent updates.
        self._attr_native_value = None
        self._update_sensor_state()  # Perform an initial state update upon creation.

    @callback
    def _handle_coordinator_update(self) -> None:
        """
        Handle updated data from the coordinator.

        This method is called by the CoordinatorEntity base class when new data is available.
        It updates the sensor's state and then calls the superclass's method, which
        schedules an update for Home Assistant to write the new state (`async_write_ha_state`).
        """
        self._update_sensor_state()
        super()._handle_coordinator_update()  # Schedules an update via async_write_ha_state.

    def _update_sensor_state(self) -> None:
        """
        Update the sensor's internal state (`_attr_native_value` and `_attr_available`)
        based on the current data from the coordinator.
        """
        # Determine availability using HdgNodeEntity's `available` property.
        # This checks:
        # 1. Coordinator's overall status (last_update_success).
        # 2. Presence of this specific node's data in coordinator.data.
        self._attr_available = super().available

        if not self._attr_available:  # Entity is not available.
            self._attr_native_value = None
            return
        raw_value_text = self.coordinator.data.get(self._node_id)
        self._attr_native_value = self._parse_value(raw_value_text)

    def _parse_as_enum_text_type(self, cleaned_value: str) -> str:
        """
        Parse value as enum text.
        Returns the direct text from the API. For more structured enum handling,
        one might map these to standardized keys using HDG_ENUM_MAPPINGS.
        """  # The mapping to human-readable text happens implicitly via HA's enum device class
        # and the translation keys/enum options defined in the entity description/const.py.
        return cleaned_value

    def _parse_datetime_value(
        self, cleaned_value: str, source_timezone_str: str
    ) -> Optional[datetime | str]:
        """
        Parse value for 'hdg_datetime_or_text' type.
        Returns a datetime object if parsable, or the original string for special
        text values like HDG_DATETIME_SPECIAL_TEXT which are valid, non-datetime states.
        This dual return type (datetime or str) is intentional.
        The input datetime string from the HDG API is assumed to represent local time
        in the timezone specified by `source_timezone_str` (from integration options).
        """  # cleaned_value is assumed to be whitespace normalized by _parse_value.
        cleaned_value_dt = cleaned_value.strip()
        if HDG_DATETIME_SPECIAL_TEXT in cleaned_value_dt.lower():
            return cleaned_value_dt
        try:  # Parse as naive, then localize.
            dt_object_naive = datetime.strptime(cleaned_value_dt, "%d.%m.%Y %H:%M")
            try:
                source_tz = ZoneInfo(source_timezone_str)
            except ZoneInfoNotFoundError:
                _LOGGER.error(
                    f"Invalid source timezone '{source_timezone_str}' configured for sensor {self.entity_id} (node {self._node_id}). "
                    f"Cannot parse datetime value '{cleaned_value_dt}'. Please correct the timezone in integration options."
                )
                return None

            dt_object_source_aware = dt_object_naive.replace(tzinfo=source_tz)
            return dt_util.as_utc(dt_object_source_aware)
        except ValueError:
            _LOGGER.debug(
                f"Node {self._node_id} ({self.entity_id}): Could not parse '{cleaned_value_dt}' as datetime. Setting to None."
            )
            return None

    def _parse_as_float_type(
        self,
        cleaned_value: str,
        formatter: Optional[str],  # Specific rounding for "iFLOAT2" to two decimal places.
    ) -> Optional[float | int]:
        """
        Parse value as float, applying formatter-specific logic for rounding
        or potential conversion to int if the float represents a whole number
        for certain formatters (e.g., iKWH, iSTD).
        """
        val_float = parse_float_from_string(cleaned_value, self._node_id, self.entity_id)
        if val_float is None:
            return None
        # If more formatters require specific precisions, a mapping could be used here.
        if formatter == "iFLOAT2":
            return round(val_float, 2)
        # For formatters representing whole numbers, return as int if applicable.
        if formatter in [
            "iKWH",
            "iMWH",
            "iSTD",
            "iMIN",
            "iSEK",
            "iLITER",
        ] and val_float == int(val_float):
            return int(val_float)
        return val_float

    def _parse_as_int_type(self, cleaned_value: str) -> Optional[int]:
        """
        Parse value as int.
        Converts to float first to robustly handle inputs like "21.0"
        which should be treated as the integer 21.
        """
        return parse_int_from_string(cleaned_value, self._node_id, self.entity_id)

    def _parse_as_text_type(self, cleaned_value: str) -> str:
        """Parse value as plain text."""
        return cleaned_value

    def _parse_as_allow_empty_string_type(self, cleaned_value: str) -> str:
        """Parse value as text, explicitly allowing empty strings."""
        # This type is handled by the initial check in _parse_value.
        return cleaned_value

    def _parse_value(self, raw_value_text: Optional[str]) -> Any | None:
        """
        Parse the raw string value from the API into the correct type for the sensor's state.

        This method uses hints from the entity_definition (e.g., 'parse_as_type', 'hdg_formatter')
        to determine the appropriate parsing logic.
        """
        if raw_value_text is None:
            return None

        parse_as_type = self._entity_definition.get("parse_as_type")
        formatter = self._entity_definition.get("hdg_formatter")
        data_type = self._entity_definition.get("hdg_data_type")  # Original data type from HDG API.

        # Determine how to clean whitespace based on entity definition.
        # Default is to only strip leading/trailing. Internal normalization is optional.
        normalize_internal_ws = self._entity_definition.get("normalize_internal_whitespace", False)
        if normalize_internal_ws:
            cleaned_value = re.sub(r"\s+", " ", raw_value_text).strip()
        else:
            cleaned_value = raw_value_text.strip()

        # Handle specific 'allow_empty_string' case first, as it's an exception to the 'not cleaned_value' rule.
        if parse_as_type == "allow_empty_string" and cleaned_value == "":
            return ""
        if not cleaned_value:
            return None  # For most other types, an empty string implies no valid data.

        # Dictionary mapping parse_as_type strings to their parsing methods.
        # Methods requiring extra arguments are handled separately below.
        _PARSERS = {
            "percent_from_string_regex": lambda cv: parse_percent_from_string(
                cv, node_id_for_log=self._node_id, entity_id_for_log=self.entity_id
            ),
            "int": self._parse_as_int_type,
            "enum_text": self._parse_as_enum_text_type,
            "text": self._parse_as_text_type,
            # 'float' and 'hdg_datetime_or_text' need extra args, handled below.
            # 'allow_empty_string' is handled above.
        }

        if parse_as_type in _PARSERS:
            return _PARSERS[parse_as_type](cleaned_value)

        # Handle parsing types that require additional arguments or special logic.
        if parse_as_type == "hdg_datetime_or_text":  # Requires timezone
            # For datetime parsing, we *must* ensure internal spaces are collapsed to one,
            # as strptime is strict. This overrides the general normalize_internal_whitespace flag
            # for the purpose of this specific parser.
            value_for_datetime_parse = re.sub(r"\s+", " ", cleaned_value).strip()
            configured_tz = self.coordinator.entry.options.get(
                CONF_SOURCE_TIMEZONE, DEFAULT_SOURCE_TIMEZONE
            )
            return self._parse_datetime_value(value_for_datetime_parse, configured_tz)

        if parse_as_type == "float":  # Requires formatter
            return self._parse_as_float_type(cleaned_value, formatter)

        if data_type == "10":  # HDG data_type "10" often indicates an enumeration.
            # If data_type is '10' (enum) but parse_as_type is not 'enum_text', this is a misconfiguration.
            # Log an error and return None instead of raising an exception, so other entities can load.
            error_msg = (
                f"Node {self._node_id} ({self.entity_id}): Misconfiguration! "
                f"HDG data_type is '10' (enum), but 'parse_as_type' is '{parse_as_type}'. "
                "Please set 'parse_as_type: \"enum_text\"' explicitly in SENSOR_DEFINITIONS."
            )
            _LOGGER.error(error_msg)
            return None  # Return None for this misconfigured entity.

        # HDG data_type "4" is text. Formatters "iVERSION" or "iREVISION" also imply text.
        if data_type == "4" or formatter in ["iVERSION", "iREVISION"]:
            _LOGGER.debug(
                f"Node {self._node_id} ({self.entity_id}): 'parse_as_type' is '{parse_as_type}', but 'data_type' is '4' or version formatter. Treating as text."
            )
            return cleaned_value

        # Fallback for HDG data_type "2" (numeric) if not explicitly 'float' or 'int'
        if data_type == "2":
            _LOGGER.debug(
                f"Node {self._node_id} ({self.entity_id}): 'parse_as_type' is '{parse_as_type}', but HDG data_type is '2' (numeric). Attempting float parsing as fallback."
            )
            return self._parse_as_float_type(cleaned_value, formatter)

        # Final fallback if no parsing rule matched. This indicates a potential gap in SENSOR_DEFINITIONS.
        _LOGGER.warning(
            f"Node {self._node_id} ({self.entity_id}): Unhandled value parsing. Raw: '{raw_value_text}', "
            f"ParseAs: {parse_as_type}, HDG Type: {data_type}, Formatter: {formatter}. Parsed: None."
        )
        return None
