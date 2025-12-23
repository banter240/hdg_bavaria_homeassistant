"""Parsing utility functions for the HDG Bavaria Boiler integration.

This module provides robust helpers for parsing and converting raw string values
from the HDG API into typed data for Home Assistant entities. It handles
locale-specific number formats, unit stripping, and various data types.
"""

from __future__ import annotations

__version__ = "0.5.1"

import html
import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, Final

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..const import (
    DEFAULT_SOURCE_TIMEZONE,
    DOMAIN,
    HDG_DATETIME_SPECIAL_TEXT,
    HEURISTICS_LOGGER_NAME,
)
from .enum_mappings import HDG_ENUM_TEXT_TO_KEY_MAPPINGS
from .logging_utils import make_log_prefix

_LOGGER = logging.getLogger(DOMAIN)
_HEURISTICS_LOGGER = logging.getLogger(HEURISTICS_LOGGER_NAME)

__all__ = ["parse_sensor_value", "format_value_for_api"]

# Regex to find the first numeric part of a string.
_NUMERIC_PART_REGEX: Final = re.compile(r"([-+]?\d*[.,]?\d+)")

# Regex to strip common units from the end of a string.
_COMMON_UNITS_REGEX: Final = re.compile(
    r"\s*(°C|K|%|Std|min|s|pa|kw|kWh|MWh|l|l/h|m3/h|bar|rpm|A|V|Hz|ppm|pH|µS/cm|mS/cm|mg/l|g/l|kg/l|m3|m|mm|cm|km|g|kg|t|Wh|MWh|kJ|MJ|kcal|Mcal|l/min|m3/min|m/s|km/h|m/h|°F|psi|mbar|hPa|kPa|MPa|GW|MW|VA|kVA|MVA|VAR|kVAR|MVAR|PF|cosΦ|lux|lm|cd|lx|W/m2|J/m2|kWh/m2|ppm|ppb|mg/m3|g/m3|kg/m3|m3/m3|l/l|g/g|kg/kg|t/t|Wh/Wh|J/J|kcal/kcal|l/min/m2|m3/min/m2|m/s/m2|km/h/m2|m/h/m2|°F/min|psi/min|mbar/min|hPa/min|kPa/min|MPa/min|GW/min|MW/min|VA/min|kVA/min|MVA/min|VAR|kVAR|MVAR|PF/min|cosΦ/min|lux/min|lm/min|cd/min|lx/min|W/m2/min|J/m2/min|kWh/m2/min|ppm/min|ppb/min|mg/m3/min|g/m3/min|kg/m3/min|t/t/min|Wh/Wh/min|J/J/min|kcal/kcal/min|Schritte)$",
    re.IGNORECASE,
)

# Datetime formats to attempt parsing, in order of preference.
_DATETIME_FORMATS: Final[list[str]] = [
    "%d.%m.%Y %H:%M",  # Standard HDG format
    "%Y-%m-%d %H:%M:%S%z",  # ISO-like format with timezone
]


def _normalize_numeric_string(value_str: str) -> str:
    """Normalize a string containing a number by standardizing separators."""
    value_str = value_str.replace(" ", "").replace("\u00a0", "")
    has_dot = "." in value_str
    has_comma = "," in value_str

    if has_dot and has_comma:
        # If both are present, assume the last one is the decimal separator.
        return (
            value_str.replace(".", "").replace(",", ".")
            if value_str.rfind(",") > value_str.rfind(".")
            else value_str.replace(",", "")
        )
    return value_str.replace(",", ".") if has_comma else value_str


def _extract_numeric_string(raw_value: str, log_prefix: str) -> str | None:
    """Extract a normalized numeric string from a raw value."""
    if raw_value.strip() == "---":
        return None

    value_no_units = _COMMON_UNITS_REGEX.sub("", raw_value).strip()
    if value_no_units != raw_value:
        _HEURISTICS_LOGGER.debug(
            "%sStripped units from '%s' to '%s'.",
            log_prefix,
            raw_value,
            value_no_units,
        )

    normalized_str = _normalize_numeric_string(value_no_units)
    if match := _NUMERIC_PART_REGEX.search(normalized_str):
        return match.group(1)

    _LOGGER.debug(
        "%sNo numeric part found in '%s' (original: '%s').",
        log_prefix,
        normalized_str,
        raw_value,
    )
    return None


def _parse_number(
    raw_value: str, target_type: type[int] | type[float], log_prefix: str
) -> int | float | None:
    """Parse a number from a string into the specified type."""
    numeric_str = _extract_numeric_string(raw_value, log_prefix)
    if numeric_str is None:
        return None
    try:
        return target_type(float(numeric_str))
    except (ValueError, TypeError):
        _LOGGER.warning(
            "%sCould not parse %s from '%s' (original: '%s').",
            log_prefix,
            target_type.__name__,
            numeric_str,
            raw_value,
        )
        return None


def _get_source_timezone(timezone_str: str, log_prefix: str) -> ZoneInfo | None:
    """Get a ZoneInfo object from a string, with error logging."""
    try:
        return ZoneInfo(timezone_str)
    except ZoneInfoNotFoundError:
        _LOGGER.error(
            "%sInvalid source timezone '%s'. Cannot parse datetime.",
            log_prefix,
            timezone_str,
        )
        return None


def _parse_datetime(
    value: str, timezone_str: str, log_prefix: str
) -> datetime | str | None:
    """Parse a datetime string into a timezone-aware datetime object."""
    if HDG_DATETIME_SPECIAL_TEXT in value.lower():
        return value

    source_tz = _get_source_timezone(timezone_str, log_prefix)
    if not source_tz:
        return None

    for fmt in _DATETIME_FORMATS:
        try:
            if "%z" in fmt:
                # Handle timezone offsets with or without colon
                val_for_fmt = value
                if ":" in val_for_fmt[-6:]:
                    val_for_fmt = val_for_fmt[:-3] + val_for_fmt[-2:]
                dt_aware = datetime.strptime(val_for_fmt, fmt)
                return dt_aware.astimezone(source_tz)

            dt_naive = datetime.strptime(value, fmt)
            return dt_naive.replace(tzinfo=source_tz)
        except ValueError:
            continue  # Try the next format

    _LOGGER.warning(
        "%sCould not parse '%s' as datetime with known formats.", log_prefix, value
    )
    return None


def _convert_enum_text_to_key(
    value: str, entity_def: dict[str, Any], log_prefix: str
) -> str:
    """Convert a raw enum text value from the boiler to its canonical key."""
    translation_key = entity_def.get("translation_key")
    if not translation_key:
        return value

    enum_map = HDG_ENUM_TEXT_TO_KEY_MAPPINGS.get(translation_key)
    if not enum_map:
        return value

    if key := next((k for text, k in enum_map.items() if text == value), None):
        _LOGGER.debug("%sMapped enum '%s' to key '%s'.", log_prefix, value, key)
        return key

    _LOGGER.warning(
        "%sEnum value '%s' not found in mapping for '%s'. Returning raw value.",
        log_prefix,
        value,
        translation_key,
    )
    return value


def format_value_for_api(numeric_value: int | float, setter_type: str) -> str:
    """Format a numeric value into the string representation expected by the HDG API."""
    if setter_type == "int":
        return str(int(round(numeric_value)))
    if setter_type == "float1":
        return f"{numeric_value:.1f}"
    if setter_type == "float2":
        return f"{numeric_value:.2f}"

    raise ValueError(f"Unknown 'setter_type' ('{setter_type}') for value.")


def _prepare_parser_and_value(
    raw_value: str | None,
    entity_definition: dict[str, Any],
    log_prefix: str,
) -> tuple[Callable[..., Any] | None, str | None]:
    """Prepare the parser and cleaned value, returning None if parsing is not possible."""
    if raw_value is None:
        return None, None

    cleaned_value = html.unescape(str(raw_value)).strip()
    parse_as_type = entity_definition.get("parse_as_type")

    if not parse_as_type or parse_as_type not in _PARSER_MAP:
        _LOGGER.warning(
            "%sUnknown or invalid parse_as_type '%s'. Returning raw value.",
            log_prefix,
            parse_as_type,
        )
        return None, cleaned_value

    return _PARSER_MAP.get(parse_as_type), cleaned_value


# --- Main Parser ---

_PARSER_MAP: Final[dict[str, Callable[..., Any]]] = {
    "int": lambda value, prefix, *args, **kwargs: _parse_number(value, int, prefix),
    "float": lambda value, prefix, *args, **kwargs: _parse_number(value, float, prefix),
    "enum_text": lambda value,
    prefix,
    entity_def,
    *args,
    **kwargs: _convert_enum_text_to_key(value, entity_def, prefix),
    "hdg_datetime_or_text": lambda value,
    prefix,
    *args,
    timezone,
    **kwargs: _parse_datetime(value, timezone, prefix),
    "text": lambda value, *args, **kwargs: value,
    "allow_empty_string": lambda value, *args, **kwargs: value,
}


def parse_sensor_value(
    raw_value: str | None,
    entity_definition: dict[str, Any],
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
    configured_timezone: str = DEFAULT_SOURCE_TIMEZONE,
) -> Any | None:
    """Parse a raw string value from the API into the appropriate type."""
    log_prefix = make_log_prefix(node_id_for_log, entity_id_for_log)
    parser, cleaned_value = _prepare_parser_and_value(
        raw_value, entity_definition, log_prefix
    )

    if parser is None:
        return cleaned_value  # Return raw or cleaned value if no parser found

    try:
        return parser(
            cleaned_value,
            log_prefix,
            entity_definition,
            timezone=configured_timezone,
        )
    except Exception as e:
        _LOGGER.warning(
            "%sError parsing value '%s' as %s: %s. Returning raw.",
            log_prefix,
            cleaned_value,
            entity_definition.get("parse_as_type"),
            e,
            exc_info=True,
        )
        return cleaned_value
