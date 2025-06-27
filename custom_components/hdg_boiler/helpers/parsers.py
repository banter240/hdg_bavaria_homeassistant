"""General parsing utility functions for the HDG Bavaria Boiler integration.

This module provides helper functions for parsing numeric values from strings,
handling locale-specific number formats, and formatting values for API communication.
It aims to robustly extract and convert data from potentially varied string inputs.
"""

from __future__ import annotations

__version__ = "0.2.0"

import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, Final, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.util import dt as dt_util

from ..const import (
    DEFAULT_SOURCE_TIMEZONE,
    DOMAIN,
    HDG_DATETIME_SPECIAL_TEXT,
    HEURISTICS_LOGGER_NAME,
)
from .logging_utils import make_log_prefix

_LOGGER = logging.getLogger(DOMAIN)
_HEURISTICS_LOGGER = logging.getLogger(HEURISTICS_LOGGER_NAME)

NUMERIC_PART_REGEX: Final = re.compile(r"([-+]?\d*\.?\d+)")
DEFAULT_PERCENT_REGEX_PATTERN: Final = r"(\d+)\s*%?[\s-]*Schritte"

DEFAULT_PERCENT_REGEX: Final = re.compile(DEFAULT_PERCENT_REGEX_PATTERN, re.IGNORECASE)

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


def extract_numeric_string(
    raw_cleaned_value: str,
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
    locale: str | None = None,
) -> str | None:
    """Extract the numeric part of a string using regex after locale-aware normalization."""
    log_prefix = make_log_prefix(node_id_for_log, entity_id_for_log)
    normalized_value_str = _normalize_value_string(
        raw_cleaned_value, locale, log_prefix, raw_cleaned_value
    )

    if normalized_value_str is None:
        return None

    if match := NUMERIC_PART_REGEX.search(normalized_value_str):
        return match.group(0)
    _LOGGER.debug(
        f"{log_prefix}No numeric part found in '{normalized_value_str}' (original: '{raw_cleaned_value}') during numeric extraction."
    )
    return None


def parse_percent_from_string(
    cleaned_value: str,
    regex_pattern: re.Pattern[str] = DEFAULT_PERCENT_REGEX,
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
) -> int | None:
    """Parse percentage from a string using a regex pattern."""
    log_prefix = make_log_prefix(node_id_for_log, entity_id_for_log)
    if match := re.search(regex_pattern, cleaned_value):
        if match.lastindex is not None and match.lastindex >= 1:
            try:
                return int(match[1])
            except ValueError:
                _LOGGER.warning(
                    f"{log_prefix}Could not parse numeric part from regex group 1 ('{match[1]}') in '{cleaned_value}' for percent regex."
                )
                return None
            except IndexError:
                _LOGGER.error(
                    f"{log_prefix}Regex pattern '{regex_pattern}' did not capture group 1 as expected from '{cleaned_value}'."
                )
                return None
        else:
            _LOGGER.warning(
                f"{log_prefix}Regex pattern '{regex_pattern}' did not find expected capturing group in '{cleaned_value}'."
            )
            return None
    _LOGGER.warning(
        f"{log_prefix}Regex did not find percentage in '{cleaned_value}' for percent regex."
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
    try:
        dt_object_naive = datetime.strptime(cleaned_value_dt, "%d.%m.%Y %H:%M")
        try:
            source_tz = ZoneInfo(source_timezone_str)
        except ZoneInfoNotFoundError:
            _LOGGER.error(
                f"Invalid source timezone '{source_timezone_str}' for sensor "
                f"(node {node_id_for_log or 'Unknown'}, entity {entity_id_for_log or 'Unknown'}). "
                f"Cannot parse datetime value '{cleaned_value_dt}'. Correct timezone in options."
            )
            return None

        dt_object_source_aware = dt_object_naive.replace(tzinfo=source_tz)
        return cast(datetime, dt_util.as_utc(dt_object_source_aware))
    except ValueError:
        _LOGGER.warning(
            f"Node {node_id_for_log} (entity {entity_id_for_log}): Could not parse '{cleaned_value_dt}' as datetime."
        )
        return None


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


_PARSERS: dict[str, Callable[[str, str | None, str | None, Any], Any | None]] = {
    "percent_from_string_regex": lambda cv,
    node_id,
    entity_id,
    _: parse_percent_from_string(
        cv, node_id_for_log=node_id, entity_id_for_log=entity_id
    ),
    "int": lambda cv, node_id, entity_id, _: parse_int_from_string(
        cv, node_id_for_log=node_id, entity_id_for_log=entity_id
    ),
    "enum_text": lambda cv, *_: cv,
    "text": lambda cv, *_: cv,
    "allow_empty_string": lambda cv, *_: cv,
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

    # Centralized dispatch table for parsing logic
    parser_map: dict[str, Callable[..., Any]] = {
        "percent_from_string_regex": parse_percent_from_string,
        "int": parse_int_from_string,
        "enum_text": lambda val, *args, **kwargs: val,
        "text": lambda val, *args, **kwargs: val,
        "allow_empty_string": lambda val, *args, **kwargs: val,
        "hdg_datetime_or_text": parse_datetime_value,
        "float": parse_as_float_type,
    }

    parse_as_type = entity_definition.get("parse_as_type")
    formatter = entity_definition.get("hdg_formatter")
    data_type = entity_definition.get("hdg_data_type")

    # Pre-process the raw value
    cleaned_value = (
        re.sub(r"\s+", " ", raw_value_text).strip()
        if entity_definition.get("normalize_internal_whitespace", False)
        else raw_value_text.strip()
    )

    if not cleaned_value:
        return "" if parse_as_type == "allow_empty_string" else None

    # Primary parsing using `parse_as_type`
    if isinstance(parse_as_type, str) and parse_as_type in parser_map:
        parser_func = parser_map[parse_as_type]
        # Prepare arguments for the specific parser
        if parse_as_type == "hdg_datetime_or_text":
            return parser_func(
                cleaned_value,
                configured_timezone,
                node_id_for_log,
                entity_id_for_log,
            )
        elif parse_as_type == "float":
            return parser_func(
                cleaned_value, formatter, node_id_for_log, entity_id_for_log
            )
        else:
            return parser_func(
                cleaned_value,
                node_id_for_log=node_id_for_log,
                entity_id_for_log=entity_id_for_log,
            )

    # Fallback parsing using `hdg_data_type` and `hdg_formatter`
    if data_type == "10" or formatter in ["iVERSION", "iREVISION"]:
        return cleaned_value
    if data_type == "4":  # Often text despite being numeric type
        return cleaned_value
    if data_type == "2":  # Generic float type
        return parse_as_float_type(
            cleaned_value, formatter, node_id_for_log, entity_id_for_log
        )

    _LOGGER.warning(
        f"Node {node_id_for_log or 'Unknown'} (entity {entity_id_for_log or 'Unknown'}): "
        f"Unhandled value parsing. Raw: '{raw_value_text}', "
        f"ParseAs: {parse_as_type}, HDG Type: {data_type}, Formatter: {formatter}. Parsed: None."
    )
    return None
