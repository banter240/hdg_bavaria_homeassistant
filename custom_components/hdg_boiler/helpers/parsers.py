"""General parsing utility functions for the HDG Bavaria Boiler integration.

This module provides helper functions for parsing numeric values from strings,
handling locale-specific number formats, and formatting values for API communication.
It aims to robustly extract and convert data from potentially varied string inputs.
"""

from __future__ import annotations

__version__ = "0.3.2"

import logging
import re
import html

from collections.abc import Callable
from datetime import datetime
from typing import Any, Final, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


from ..const import (
    DEFAULT_SOURCE_TIMEZONE,
    DOMAIN,
    HDG_DATETIME_SPECIAL_TEXT,
    HEURISTICS_LOGGER_NAME,
)
from .logging_utils import make_log_prefix
from .enum_mappings import HDG_ENUM_TEXT_TO_KEY_MAPPINGS


_LOGGER = logging.getLogger(DOMAIN)
_HEURISTICS_LOGGER = logging.getLogger(HEURISTICS_LOGGER_NAME)

NUMERIC_PART_REGEX: Final = re.compile(r"([-+]?\d*\.?\d+)")


KNOWN_LOCALE_SEPARATORS: Final[dict[str, dict[str, str]]] = {
    "en_US": {"decimal_point": ".", "thousands_sep": ","},
    "de_DE": {"decimal_point": ",", "thousands_sep": "."},
    "en_GB": {"decimal_point": ".", "thousands_sep": ","},
    "fr_FR": {
        "decimal_point": ",",
        "thousands_sep": " ",
    },
    "it_IT": {"decimal_point": ",", "thousands_sep": "."},
    "es_ES": {"decimal_point": ",", "thousands_sep": "."},
}


def _convert_enum_text_to_key(
    raw_value: str,
    entity_definition: dict[str, Any],
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
) -> str:
    """Convert a raw enum text value from the boiler to its canonical key.

    This function uses the `HDG_ENUM_TEXT_TO_KEY_MAPPINGS` to find the
    corresponding canonical key for a given raw text value. If a direct
    mapping is not found, it logs a warning and returns the raw value.
    """
    log_prefix = make_log_prefix(node_id_for_log, entity_id_for_log)
    translation_key = entity_definition.get("translation_key")

    if translation_key and translation_key in HDG_ENUM_TEXT_TO_KEY_MAPPINGS:
        enum_map = HDG_ENUM_TEXT_TO_KEY_MAPPINGS[translation_key]
        _LOGGER.debug(
            f"{log_prefix}Attempting to map raw enum value '{raw_value}' for translation key '{translation_key}'."
        )
        for human_readable_text, canonical_key in enum_map.items():
            if human_readable_text == raw_value:
                _LOGGER.debug(
                    f"{log_prefix}Mapped raw enum '{raw_value}' to key '{canonical_key}'."
                )
                return canonical_key
        _LOGGER.warning(
            f"{log_prefix}Raw enum value '{raw_value}' not found in mapping for '{translation_key}'. "
            "Returning raw value. Please update enum_mappings.py if this is a new valid value."
        )
    return raw_value


def _get_locale_separators_from_known_list(
    locale_str: str,
) -> tuple[str, str] | None:
    """Retrieve decimal and thousands separators for a given locale from a predefined list."""
    if locale_str in KNOWN_LOCALE_SEPARATORS:
        conv = KNOWN_LOCALE_SEPARATORS[locale_str]
        return conv["decimal_point"], conv["thousands_sep"]
    return None


def _normalize_string_by_locale(
    value_str: str, locale_str: str, log_prefix: str, raw_cleaned_value_for_log: str
) -> str | None:
    """Normalize a string using locale-specific decimal and thousands separators."""
    normalized_value = value_str
    if separators := _get_locale_separators_from_known_list(locale_str):
        decimal_sep, thousands_sep = separators
        if thousands_sep:
            normalized_value = normalized_value.replace(thousands_sep, "")
        if decimal_sep and decimal_sep != ".":
            normalized_value = normalized_value.replace(decimal_sep, ".")
        _HEURISTICS_LOGGER.debug(
            f"{log_prefix}Normalized '{raw_cleaned_value_for_log}' to '{normalized_value}' "
            f"using pre-defined locale '{locale_str}' (dec: '{decimal_sep}', thou: '{thousands_sep}')"
        )
        return normalized_value
    else:
        _LOGGER.warning(
            f"{log_prefix}Locale '{locale_str}' not in pre-defined list for numeric parsing. "
            "Falling back to heuristic."
        )
        return None


def _normalize_string_by_heuristic(
    value_str: str, log_prefix: str, raw_cleaned_value_for_log: str
) -> str | None:
    """Normalize a string using a heuristic for mixed decimal/thousands separators."""
    if " " in value_str or "\u00a0" in value_str:
        original_for_space_log = value_str
        value_str = value_str.replace(" ", "").replace("\u00a0", "")
        _HEURISTICS_LOGGER.debug(
            f"{log_prefix}Heuristic: removed spaces/NBSPs from '{original_for_space_log}', now '{value_str}'."
        )

    if "." in value_str and "," in value_str:
        last_dot_pos = value_str.rfind(".")
        last_comma_pos = value_str.rfind(",")
        if last_comma_pos > last_dot_pos:
            normalized_str = value_str.replace(".", "").replace(",", ".")
            _HEURISTICS_LOGGER.debug(
                f"{log_prefix}Heuristic: mixed separators in '{value_str}', assuming European, normalized to '{normalized_str}'."
            )
            return normalized_str
        elif last_dot_pos > last_comma_pos:
            normalized_str = value_str.replace(",", "")
            _HEURISTICS_LOGGER.debug(
                f"{log_prefix}Heuristic: mixed separators in '{value_str}', assuming US, normalized to '{normalized_str}'."
            )
            return normalized_str
        _LOGGER.warning(
            f"{log_prefix}Heuristic: Ambiguous mixed separators in '{value_str}'. Unable to normalize reliably."
        )
        return None
    elif "," in value_str:
        normalized_str = value_str.replace(",", ".")
        _HEURISTICS_LOGGER.debug(
            f"{log_prefix}Heuristic: replaced comma with dot in '{raw_cleaned_value_for_log}', now '{normalized_str}'."
        )
        return normalized_str
    return value_str


def _normalize_value_string(
    value_str: str,
    locale_str: str | None,
    log_prefix: str,
    raw_cleaned_value_for_log: str,
) -> str | None:
    """Normalize a string using locale-specific rules or heuristics."""
    normalized_value_str: str | None = None
    if locale_str:
        normalized_value_str = _normalize_string_by_locale(
            value_str, locale_str, log_prefix, raw_cleaned_value_for_log
        )
        if normalized_value_str is None:
            _HEURISTICS_LOGGER.debug(
                f"{log_prefix}Locale normalization failed for '{raw_cleaned_value_for_log}', attempting heuristic."
            )
            normalized_value_str = _normalize_string_by_heuristic(
                value_str, log_prefix, raw_cleaned_value_for_log
            )
    else:
        normalized_value_str = _normalize_string_by_heuristic(
            value_str, log_prefix, raw_cleaned_value_for_log
        )
    return normalized_value_str


COMMON_UNITS_REGEX: Final = re.compile(
    r"\s*(°C|K|%|Std|min|s|pa|kw|kWh|MWh|l|l/h|m3/h|bar|rpm|A|V|Hz|ppm|pH|µS/cm|mS/cm|mg/l|g/l|kg/l|m3|m|mm|cm|km|g|kg|t|Wh|MWh|kJ|MJ|kcal|Mcal|l/min|m3/min|m/s|km/h|m/h|°F|psi|mbar|hPa|kPa|MPa|GW|MW|VA|kVA|MVA|VAR|kVAR|MVAR|PF|cosΦ|lux|lm|cd|lx|W/m2|J/m2|kWh/m2|ppm|ppb|mg/m3|g/m3|kg/m3|m3/m3|l/l|g/g|kg/kg|t/t|Wh/Wh|J/J|kcal/kcal|l/min/m2|m3/min/m2|m/s/m2|km/h/m2|m/h/m2|°F/min|psi/min|mbar/min|hPa/min|kPa/min|MPa/min|GW/min|MW/min|VA/min|kVA/min|MVA/min|VAR|kVAR|MVAR|PF/min|cosΦ/min|lux/min|lm/min|cd/min|lx/min|W/m2/min|J/m2/min|kWh/m2/min|ppm/min|ppb/min|mg/m3/min|g/m3/min|kg/m3/min|t/t/min|Wh/Wh/min|J/J/min|kcal/kcal/min|Schritte)",
    re.IGNORECASE,
)


def extract_numeric_string(
    raw_cleaned_value: str,
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
    locale: str | None = None,
) -> str | None:
    """Extract the numeric part of a string after stripping units and locale-aware normalization."""
    log_prefix = make_log_prefix(node_id_for_log, entity_id_for_log)

    # Remove common units first
    value_without_units = COMMON_UNITS_REGEX.sub("", raw_cleaned_value).strip()
    if value_without_units != raw_cleaned_value:
        _HEURISTICS_LOGGER.debug(
            f"{log_prefix}Stripped units from '{raw_cleaned_value}' to '{value_without_units}'."
        )

    normalized_value_str = _normalize_value_string(
        value_without_units, locale, log_prefix, value_without_units
    )

    if normalized_value_str is None:
        return None

    if match := NUMERIC_PART_REGEX.search(normalized_value_str):
        return match.group(0)
    _LOGGER.debug(
        f"{log_prefix}No numeric part found in '{normalized_value_str}' (original: '{raw_cleaned_value}') during numeric extraction."
    )
    return None


def format_value_for_api(numeric_value: int | float, setter_type: str) -> str:
    """Format a numeric value into the string representation expected by the HDG API."""
    if setter_type == "int":
        return str(int(round(numeric_value)))
    elif setter_type == "float1":
        return f"{numeric_value:.1f}"
    elif setter_type == "float2":
        return f"{numeric_value:.2f}"
    else:
        msg = f"Unknown 'setter_type' ('{setter_type}') for value '{numeric_value}'."
        _LOGGER.error(msg)
        raise ValueError(msg)


def parse_int_from_string(
    raw_value: str,
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
) -> int | None:
    """Parse an integer from a string, robustly handling potential float representations."""
    numeric_part_str = extract_numeric_string(
        raw_value, node_id_for_log, entity_id_for_log
    )
    if numeric_part_str is None:
        return None
    try:
        return int(float(numeric_part_str))  # type: ignore[arg-type]
    except ValueError:
        log_prefix = make_log_prefix(node_id_for_log, entity_id_for_log)
        _LOGGER.warning(
            f"{log_prefix}Could not parse int value from '{numeric_part_str}' (original: '{raw_value}')."
        )
        return None


def parse_float_from_string(
    raw_value: str,
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
) -> float | None:
    """Parse a float from a string, extracting the numeric part first."""
    numeric_part_str = extract_numeric_string(
        raw_value, node_id_for_log, entity_id_for_log
    )
    if numeric_part_str is None:
        return None
    try:
        return float(numeric_part_str)
    except ValueError:
        log_prefix = make_log_prefix(node_id_for_log, entity_id_for_log)
        _LOGGER.warning(
            f"{log_prefix}Could not parse float value from '{numeric_part_str}' (original: '{raw_value}')."
        )
        return None


def parse_datetime_value(
    cleaned_value: str,
    source_timezone_str: str,
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
) -> datetime | str | None:
    """Parse a string value that represents a datetime or special text."""
    cleaned_value_dt = cleaned_value.strip().replace("&nbsp;", " ")
    if HDG_DATETIME_SPECIAL_TEXT in cleaned_value_dt.lower():
        return cleaned_value_dt

    log_prefix = make_log_prefix(node_id_for_log, entity_id_for_log)

    # Attempt to parse with the primary format (DD.MM.YYYY HH:MM)
    try:
        dt_object_naive = datetime.strptime(cleaned_value_dt, "%d.%m.%Y %H:%M")
    except ValueError:
        # If primary format fails, try the alternative format (YYYY-MM-DD HH:MM:SS+HH:MM)
        # First, remove colon from timezone offset if present, as %z does not support it
        if (
            "+" in cleaned_value_dt
            and ":" in cleaned_value_dt[cleaned_value_dt.rfind("+") :]
        ):
            cleaned_value_dt = (
                cleaned_value_dt[: cleaned_value_dt.rfind(":")]
                + cleaned_value_dt[cleaned_value_dt.rfind(":") + 1 :]
            )
        elif (
            "-" in cleaned_value_dt
            and ":" in cleaned_value_dt[cleaned_value_dt.rfind("-") :]
        ):
            cleaned_value_dt = (
                cleaned_value_dt[: cleaned_value_dt.rfind(":")]
                + cleaned_value_dt[cleaned_value_dt.rfind(":") + 1 :]
            )
        try:
            dt_object_naive = datetime.strptime(cleaned_value_dt, "%Y-%m-%d %H:%M:%S%z")
        except ValueError as e:
            _LOGGER.warning(
                f"{log_prefix}Could not parse '{cleaned_value_dt}' as datetime with either format. Error: {e}"
            )
            return None

    try:
        source_tz = ZoneInfo(source_timezone_str)
    except ZoneInfoNotFoundError:
        _LOGGER.error(
            f"{log_prefix}Invalid source timezone '{source_timezone_str}'. "
            f"Cannot parse datetime value '{cleaned_value_dt}'. Correct timezone in options."
        )
        return None

    dt_object_source_aware = dt_object_naive.replace(tzinfo=source_tz)
    return cast(datetime, dt_object_source_aware)


def parse_as_float_type(
    cleaned_value: str,
    formatter: str | None,
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
) -> float | int | None:
    """Parse a string value as a float, with specific handling for certain formatters."""
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
        return int(val_float)
    return val_float


_PARSERS: dict[str, Callable[..., Any]] = {
    "int": lambda cv, node_id, entity_id, _: parse_int_from_string(
        cv, node_id_for_log=node_id, entity_id_for_log=entity_id
    ),
    "enum_text": lambda cv, *args: cv,
    "text": lambda cv, *args: cv,
    "allow_empty_string": lambda cv, *args: cv,
    "hdg_datetime_or_text": lambda cv, node_id, entity_id, tz: parse_datetime_value(
        cv, tz, node_id_for_log=node_id, entity_id_for_log=entity_id
    ),
    "float": lambda cv, node_id, entity_id, formatter: parse_as_float_type(
        cv, formatter, node_id_for_log=node_id, entity_id_for_log=entity_id
    ),
}


def parse_sensor_value(
    raw_value_text: str | None,
    entity_definition: dict[str, Any],
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
    configured_timezone: str = DEFAULT_SOURCE_TIMEZONE,
) -> Any | None:
    """Parse the raw string value from the API into the appropriate type for the sensor state."""
    if raw_value_text is None:
        return None

    parse_as_type = entity_definition.get("parse_as_type")
    hdg_formatter = entity_definition.get("hdg_formatter")

    log_prefix = make_log_prefix(node_id_for_log, entity_id_for_log)

    # Clean the raw value by unescaping HTML entities and stripping whitespace
    cleaned_value = html.unescape(str(raw_value_text)).strip()

    # For enums, the state should be the raw internal key from the boiler.
    # Home Assistant's frontend will handle the translation based on the
    # entity's translation_key and the corresponding state map in the translation files.
    if parse_as_type == "enum_text":
        return _convert_enum_text_to_key(
            cleaned_value, entity_definition, node_id_for_log, entity_id_for_log
        )

    if isinstance(parse_as_type, str) and (parser := _PARSERS.get(parse_as_type)):
        try:
            if parse_as_type == "hdg_datetime_or_text":
                return parser(
                    cleaned_value,
                    node_id_for_log,
                    entity_id_for_log,
                    configured_timezone,
                )
            elif parse_as_type == "float":
                return parser(
                    cleaned_value, node_id_for_log, entity_id_for_log, hdg_formatter
                )
            else:
                return parser(cleaned_value, node_id_for_log, entity_id_for_log, None)
        except Exception as e:
            _LOGGER.warning(
                f"{log_prefix}Error parsing value '{cleaned_value}' as {parse_as_type}: {e}. Returning raw."
            )
            return raw_value_text
    else:
        _LOGGER.warning(
            f"{log_prefix}Unknown or invalid parse_as_type '{parse_as_type}'. Returning raw value '{raw_value_text}'."
        )
        return raw_value_text
