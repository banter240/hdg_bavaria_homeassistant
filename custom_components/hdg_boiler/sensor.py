"""
Sensor platform for the HDG Bavaria Boiler integration.

This module creates and manages sensor entities that display various data
points read from the HDG Bavaria boiler system, utilizing the data update
coordinator and entity definitions.
"""

from __future__ import annotations

__version__ = "0.8.27"

import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SOURCE_TIMEZONE,
    DEFAULT_SOURCE_TIMEZONE,
    DOMAIN,
    HDG_DATETIME_SPECIAL_TEXT,
)
from .coordinator import HdgDataUpdateCoordinator
from .definitions import (
    SENSOR_DEFINITIONS,
    SensorDefinition,
)
from .entity import HdgNodeEntity
from .utils import (
    parse_float_from_string,
    parse_int_from_string,
    parse_percent_from_string,
    strip_hdg_node_suffix,
)

_LOGGER = logging.getLogger(DOMAIN)

# Dictionary mapping 'parse_as_type' strings from SENSOR_DEFINITIONS to
# corresponding parsing methods. These methods take the cleaned string value
# and optional logging context arguments (node_id, entity_id).
_PARSERS: dict[str, Callable[[str, str | None, str | None], Any | None]] = {
    "percent_from_string_regex": lambda cv,
    node_id,
    entity_id: parse_percent_from_string(
        cv, node_id_for_log=node_id, entity_id_for_log=entity_id
    ),
    "int": lambda cv, node_id, entity_id: parse_int_from_string(
        cv, node_id_for_log=node_id, entity_id_for_log=entity_id
    ),
    "enum_text": lambda cv, *_: cv,
    "text": lambda cv, *_: cv,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Set up HDG Bavaria sensor entities based on a configuration entry.

    Iterates through SENSOR_DEFINITIONS, creating sensor entities for those
    defined with `ha_platform: "sensor"`.
    """
    coordinator: HdgDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    entities: list[HdgBoilerSensor] = []

    for unique_id_suffix, entity_definition_dict in SENSOR_DEFINITIONS.items():
        entity_def = cast(SensorDefinition, entity_definition_dict)

        if entity_def.get("ha_platform") == "sensor":
            description = SensorEntityDescription(
                key=unique_id_suffix,
                name=None,
                icon=entity_def.get("icon"),
                device_class=cast(
                    SensorDeviceClass | None, entity_def.get("ha_device_class")
                ),
                native_unit_of_measurement=entity_def.get(
                    "ha_native_unit_of_measurement"
                ),
                state_class=entity_def.get("ha_state_class"),
                entity_category=entity_def.get("entity_category"),
                translation_key=entity_def.get("translation_key"),
            )
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
    Represents an HDG Bavaria Boiler sensor entity.

    This class is responsible for parsing raw data received from the
    HdgDataUpdateCoordinator into a displayable sensor state, according
    to its entity definition.
    """

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        entity_description: SensorEntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """
        Initialize the HDG Boiler sensor entity.

        Args:
            coordinator: The HdgDataUpdateCoordinator for managing entity data.
            entity_description: Standard Home Assistant SensorEntityDescription.
            entity_definition: Custom entity definition from SENSOR_DEFINITIONS.
        """
        hdg_api_node_id_from_def = entity_definition["hdg_node_id"]
        super().__init__(
            coordinator,
            strip_hdg_node_suffix(hdg_api_node_id_from_def),
            cast(dict[str, Any], entity_definition),
        )
        self.entity_description = entity_description

        self._attr_native_value = None
        self._update_sensor_state()

        _LOGGER.debug(f"HdgBoilerSensor {self.entity_description.key}: Initialized.")

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the HdgDataUpdateCoordinator."""
        self._update_sensor_state()
        super()._handle_coordinator_update()

    def _update_sensor_state(self) -> None:
        """Update the sensor's internal state from the coordinator's data."""
        self._attr_available = super().available

        if not self._attr_available:
            self._attr_native_value = None
            return
        raw_value_text = self.coordinator.data.get(self._node_id)
        self._attr_native_value = self._parse_value(raw_value_text)

    def _parse_datetime_value(
        self,
        cleaned_value: str,
        source_timezone_str: str,
    ) -> datetime | str | None:
        """
        Parse a string value that represents a datetime or special text.

        Attempts to parse "DD.MM.YYYY HH:MM" format, localizes it using
        `source_timezone_str`, and converts to UTC. If the value contains
        `HDG_DATETIME_SPECIAL_TEXT`, it returns the original string.

        Args:
            cleaned_value: The string value to parse.
            source_timezone_str: The IANA timezone string for the source datetime.

        Returns:
            A UTC datetime object if parsing is successful, the original string
            if it's a special text, or None if parsing fails.
        """
        cleaned_value_dt = cleaned_value.strip()
        if HDG_DATETIME_SPECIAL_TEXT in cleaned_value_dt.lower():
            return cast(str, cleaned_value_dt)
        try:
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
            return cast(datetime, dt_util.as_utc(dt_object_source_aware))
        except ValueError:
            _LOGGER.debug(
                f"Node {self._node_id} ({self.entity_id}): Could not parse '{cleaned_value_dt}' as datetime. Setting to None."
            )
            return None

    def _parse_as_float_type(
        self,
        cleaned_value: str,
        formatter: str | None,
    ) -> float | int | None:
        """
        Parse a string value as a float, with specific handling for certain formatters.

        If the `formatter` indicates a value that is typically an integer (like kWh or hours),
        and the parsed float is a whole number, it's returned as an int.
        For "iFLOAT2", it rounds to two decimal places.

        Args:
            cleaned_value: The string value to parse.
            formatter: The 'hdg_formatter' hint from SENSOR_DEFINITIONS.

        Returns:
            The parsed float or int, or None if parsing fails.
        """
        val_float = parse_float_from_string(
            cleaned_value, self._node_id, self.entity_id
        )
        if val_float is None:
            return None
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

    def _parse_value(self, raw_value_text: str | None) -> Any | None:
        """
        Parse the raw string value from the API into the appropriate type for the sensor state.

        This method uses hints from the entity's definition (`parse_as_type`,
        `hdg_formatter`, `hdg_data_type`) to determine the correct parsing strategy.

        Args:
            raw_value_text: The raw string value received from the API.

        Returns:
            The parsed value suitable for the sensor's state, or None if parsing fails
            or the raw value is None/empty (unless 'allow_empty_string' is specified).
        """
        if raw_value_text is None:
            return None

        parse_as_type = self._entity_definition.get("parse_as_type")
        formatter = self._entity_definition.get("hdg_formatter")
        data_type = self._entity_definition.get("hdg_data_type")

        if self._entity_definition.get("normalize_internal_whitespace", False):
            cleaned_value = re.sub(r"\s+", " ", raw_value_text).strip()
        else:
            cleaned_value = raw_value_text.strip()

        if parse_as_type == "allow_empty_string" and cleaned_value == "":
            return ""
        if not cleaned_value and parse_as_type != "allow_empty_string":
            return None  # Most types treat empty string as no valid data.

        if parse_as_type in _PARSERS:
            parser_func = cast(
                Callable[[str, str | None, str | None], Any | None],
                _PARSERS[parse_as_type],
            )
            return parser_func(cleaned_value, self._node_id, self.entity_id)

        if parse_as_type == "hdg_datetime_or_text":
            value_for_datetime_parse = re.sub(r"\s+", " ", cleaned_value).strip()
            configured_tz = self.coordinator.entry.options.get(
                CONF_SOURCE_TIMEZONE, DEFAULT_SOURCE_TIMEZONE
            )
            return self._parse_datetime_value(value_for_datetime_parse, configured_tz)

        if parse_as_type == "float":
            return self._parse_as_float_type(cleaned_value, formatter)

        if parse_as_type is not None:  # A parse_as_type was defined but not handled.
            _LOGGER.warning(
                f"Node {self._node_id} ({self.entity_id}): Unknown 'parse_as_type' '{parse_as_type}'. "
                f"Raw value: '{raw_value_text}', Cleaned: '{cleaned_value}'. Please add a parser or correct the definition."
            )
            return None

        # Fallback logic if 'parse_as_type' is not defined.
        if data_type == "10":  # HDG data_type "10" indicates an enumeration.
            return cleaned_value  # Assume it's enum_text.

        if data_type == "4" or formatter in [
            "iVERSION",
            "iREVISION",
        ]:  # HDG data_type "4" is text.
            return cleaned_value

        if data_type == "2":  # HDG data_type "2" is numeric.
            return self._parse_as_float_type(cleaned_value, formatter)

        _LOGGER.warning(
            f"Node {self._node_id} ({self.entity_id}): Unhandled value parsing. Raw: '{raw_value_text}', "
            f"ParseAs: {parse_as_type}, HDG Type: {data_type}, Formatter: {formatter}. Parsed: None."
        )
        return None
