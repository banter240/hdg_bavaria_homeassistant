"""
Sensor value parsing utility functions for the HDG Bavaria Boiler integration.

This module offers utility functions to parse raw string values received from
the HDG API into appropriate Python data types suitable for Home Assistant
sensor entities. It handles various data formats, including numbers, text,
enumerations, and datetimes, with considerations for localization and specific
HDG API quirks.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.util import dt as dt_util

from ..const import (
    DEFAULT_SOURCE_TIMEZONE,
    DOMAIN,
    HDG_DATETIME_SPECIAL_TEXT,
)
from .parsing_utils import (
    parse_float_from_string,
    parse_int_from_string,
    parse_percent_from_string,
)

_LOGGER = logging.getLogger(DOMAIN)
__version__ = "0.1.1"


# Dictionary mapping 'parse_as_type' strings from SENSOR_DEFINITIONS to
# corresponding parsing methods. These methods take the cleaned string value
# and optional logging context arguments (node_id, entity_id).
# This was originally in sensor.py
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


def parse_datetime_value(
    cleaned_value: str,
    source_timezone_str: str,
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
) -> datetime | str | None:
    """
    Parse a string value that represents a datetime or special text.

    Handles HDG's specific "größer 7 tage" text and standard datetime formats.
    Converts naive datetimes to UTC using the provided source timezone.
    """
    # Ensure consistent handling of whitespace for datetime string comparison and parsing.
    cleaned_value_dt = cleaned_value.strip()
    if HDG_DATETIME_SPECIAL_TEXT in cleaned_value_dt.lower():
        return cleaned_value_dt  # Return as string
    try:
        dt_object_naive = datetime.strptime(cleaned_value_dt, "%d.%m.%Y %H:%M")
        try:
            source_tz = ZoneInfo(source_timezone_str)
        except ZoneInfoNotFoundError:
            _LOGGER.error(
                f"Invalid source timezone '{source_timezone_str}' configured for sensor "
                f"(node {node_id_for_log or 'Unknown'}, entity {entity_id_for_log or 'Unknown'}). "
                f"Cannot parse datetime value '{cleaned_value_dt}'. Please correct the timezone in integration options."
            )
            return None

        dt_object_source_aware = dt_object_naive.replace(tzinfo=source_tz)
        return cast(datetime, dt_util.as_utc(dt_object_source_aware))
    except ValueError:
        _LOGGER.debug(
            f"Node {node_id_for_log or 'Unknown'} (entity {entity_id_for_log or 'Unknown'}): "
            f"Could not parse '{cleaned_value_dt}' as datetime. Setting to None."
        )
        return None


def parse_as_float_type(
    cleaned_value: str,
    formatter: str | None,
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
) -> float | int | None:
    """
    Parse a string value as a float, with specific handling for certain formatters.

    Some HDG formatters imply integer representation despite being numeric (e.g., "iKWH").
    This function attempts to return an int if the float value is whole for such cases.
    """
    val_float = parse_float_from_string(
        cleaned_value, node_id_for_log, entity_id_for_log
    )
    if val_float is None:
        return None
    if formatter == "iFLOAT2":
        return round(val_float, 2)

    if formatter in [
        "iKWH",
        "iMWH",
        "iSTD",
        "iMIN",
        "iSEK",
        "iLITER",
    ] and val_float == int(val_float):
        # If the value is a whole number for these unit types, return as int.
        return int(val_float)
    return val_float


def parse_sensor_value(
    raw_value_text: str | None,
    entity_definition: dict[
        str, Any
    ],  # Using dict for flexibility from SENSOR_DEFINITIONS
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
    configured_timezone: str = DEFAULT_SOURCE_TIMEZONE,
) -> Any | None:
    """
    Parse the raw string value from the API into the appropriate type for the sensor state.

    This function acts as a dispatcher based on 'parse_as_type' and 'hdg_data_type'
    defined in the entity_definition. It handles various parsing strategies,
    including numeric types, text, enums, and datetimes.
    """
    # Initial validation and cleaning of the raw input value.
    if raw_value_text is None:
        return None

    parse_as_type = entity_definition.get("parse_as_type")
    formatter = entity_definition.get("hdg_formatter")
    data_type = entity_definition.get("hdg_data_type")

    # Normalize internal whitespace if specified by the definition.
    if entity_definition.get("normalize_internal_whitespace", False):
        cleaned_value = re.sub(r"\s+", " ", raw_value_text).strip()
    else:
        cleaned_value = raw_value_text.strip()

    # Handle cases where an empty string is a valid state or where empty means unavailable.
    if parse_as_type == "allow_empty_string" and cleaned_value == "":
        return ""
    if not cleaned_value and parse_as_type != "allow_empty_string":
        return None

    # Use predefined parsers if 'parse_as_type' matches a key in _PARSERS.
    if parse_as_type in _PARSERS:
        parser_func = cast(
            Callable[[str, str | None, str | None], Any | None],
            # Ensure the correct signature for the parser function.
            _PARSERS[parse_as_type],
        )
        return parser_func(cleaned_value, node_id_for_log, entity_id_for_log)

    if parse_as_type == "hdg_datetime_or_text":
        value_for_datetime_parse = re.sub(r"\s+", " ", cleaned_value).strip()
        return parse_datetime_value(
            value_for_datetime_parse,
            configured_timezone,
            node_id_for_log,
            entity_id_for_log,
        )

    # Handle generic float parsing.
    if parse_as_type == "float":
        return parse_as_float_type(
            cleaned_value, formatter, node_id_for_log, entity_id_for_log
        )

    if parse_as_type is not None:
        # Log a warning if 'parse_as_type' is defined but not recognized.
        _LOGGER.warning(
            f"Node {node_id_for_log or 'Unknown'} (entity {entity_id_for_log or 'Unknown'}): Unknown 'parse_as_type' '{parse_as_type}'. "
            f"Raw value: '{raw_value_text}', Cleaned: '{cleaned_value}'. Please add a parser or correct the definition."
        )
        return None

    if data_type == "10":
        # HDG data type "10" is typically text or an enum; return cleaned string.
        return cleaned_value
    if data_type == "4" or formatter in ["iVERSION", "iREVISION"]:
        # HDG data type "4" or specific formatters indicate text.
        return cleaned_value
    if data_type == "2":
        # HDG data type "2" is numeric; parse as float.
        return parse_as_float_type(
            cleaned_value, formatter, node_id_for_log, entity_id_for_log
        )

    # Log a warning if no parsing strategy matched.
    _LOGGER.warning(
        f"Node {node_id_for_log or 'Unknown'} (entity {entity_id_for_log or 'Unknown'}): Unhandled value parsing. Raw: '{raw_value_text}', "
        f"ParseAs: {parse_as_type}, HDG Type: {data_type}, Formatter: {formatter}. Parsed: None."
    )
    return None
