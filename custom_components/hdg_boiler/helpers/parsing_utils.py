"""General parsing utility functions for the HDG Bavaria Boiler integration.

This module provides helper functions for parsing numeric values from strings,
handling locale-specific number formats, and formatting values for API communication.
It aims to robustly extract and convert data from potentially varied string inputs.
"""

from __future__ import annotations

__version__ = "0.1.1"

import logging
import re
from typing import Final

from ..const import DOMAIN
from .logging_utils import make_log_prefix

_LOGGER = logging.getLogger(DOMAIN)

NUMERIC_PART_REGEX: Final = re.compile(r"([-+]?\d*\.?\d+)")
DEFAULT_PERCENT_REGEX_PATTERN: Final = r"(\d+)\s*%-Schritte"
DEFAULT_PERCENT_REGEX: Final = re.compile(DEFAULT_PERCENT_REGEX_PATTERN)

# Predefined locale separators to avoid global pylocale.setlocale
KNOWN_LOCALE_SEPARATORS: Final[dict[str, dict[str, str]]] = {
    "en_US": {"decimal_point": ".", "thousands_sep": ","},
    "de_DE": {"decimal_point": ",", "thousands_sep": "."},
    "en_GB": {"decimal_point": ".", "thousands_sep": ","},
    "fr_FR": {
        "decimal_point": ",",
        "thousands_sep": " ",
    },  # NBSP often, but space is common
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
        _LOGGER.debug(
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
        _LOGGER.debug(
            f"{log_prefix}Heuristic: removed spaces/NBSPs from '{original_for_space_log}', now '{value_str}'."
        )

    if "." in value_str and "," in value_str:
        last_dot_pos = value_str.rfind(".")
        last_comma_pos = value_str.rfind(",")
        if last_comma_pos > last_dot_pos:
            normalized_str = value_str.replace(".", "").replace(",", ".")
            _LOGGER.debug(
                f"{log_prefix}Heuristic: mixed separators in '{value_str}', assuming European, normalized to '{normalized_str}'."
            )
            return normalized_str
        elif last_dot_pos > last_comma_pos:
            normalized_str = value_str.replace(",", "")
            _LOGGER.debug(
                f"{log_prefix}Heuristic: mixed separators in '{value_str}', assuming US, normalized to '{normalized_str}'."
            )
            return normalized_str
        _LOGGER.warning(
            f"{log_prefix}Heuristic: Ambiguous mixed separators in '{value_str}'. Unable to normalize reliably."
        )
        return None
    elif "," in value_str:
        normalized_str = value_str.replace(",", ".")
        _LOGGER.debug(
            f"{log_prefix}Heuristic: replaced comma with dot in '{raw_cleaned_value_for_log}', now '{normalized_str}'."
        )
        return normalized_str
    return value_str


def extract_numeric_string(
    raw_cleaned_value: str,
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
    locale: str | None = None,
) -> str | None:
    """Extract the numeric part of a string using regex after locale-aware normalization."""
    value_str = raw_cleaned_value
    log_prefix = make_log_prefix(node_id_for_log, entity_id_for_log)
    normalized_value_str: str | None = None

    if locale:
        normalized_value_str = _normalize_string_by_locale(
            value_str, locale, log_prefix, raw_cleaned_value
        )
        if normalized_value_str is None:
            _LOGGER.debug(
                f"{log_prefix}Locale normalization failed for '{raw_cleaned_value}', attempting heuristic."
            )
            normalized_value_str = _normalize_string_by_heuristic(
                value_str, log_prefix, raw_cleaned_value
            )
    else:
        normalized_value_str = _normalize_string_by_heuristic(
            value_str, log_prefix, raw_cleaned_value
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
    _LOGGER.debug(
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
