"""
Utility functions for the HDG Bavaria Boiler integration.

This module provides a collection of helper functions utilized across various
parts of the HDG Bavaria Boiler integration. These include utilities for
node ID manipulation, URL normalization, string parsing, and value formatting.
"""

from __future__ import annotations

__version__ = "0.6.21"

import ipaddress
import logging
import re
from typing import Any, Final
from urllib.parse import quote, urlparse, urlunparse

from .const import DOMAIN, KNOWN_HDG_API_SETTER_SUFFIXES

_LOGGER = logging.getLogger(DOMAIN)

# Pre-compiled regex for efficiently extracting numeric parts from strings.
# Finds the first sequence of digits, optional sign, and optional decimal point with digits.
NUMERIC_PART_REGEX: Final = re.compile(r"([-+]?\d*\.?\d+)")
# Default regex pattern for percent parsing (German output "X %-Schritte").
DEFAULT_PERCENT_REGEX_PATTERN: Final = r"(\d+)\s*%-Schritte"

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


def strip_hdg_node_suffix(node_id_with_suffix: str) -> str:
    """
    Remove a known HDG API setter suffix (T, U, V, W, X, Y, case-insensitive) if present.

    Args:
        node_id_with_suffix: The node ID string, potentially with a suffix.

    Returns:
        The base node ID (numeric part if a known suffix was present, otherwise the original string).
    """
    if (
        node_id_with_suffix
        and node_id_with_suffix[-1].upper() in KNOWN_HDG_API_SETTER_SUFFIXES
    ):
        return node_id_with_suffix[:-1]
    return node_id_with_suffix


def normalize_host_for_scheme(host_address: str) -> str:
    """
    Normalize a host address string, particularly for IPv6 addresses and ports. Uses
    urllib.parse.urlparse and ipaddress to robustly handle IPv4, IPv6 addresses (with or
    without brackets), and optional port numbers.

    The input 'host_address' is assumed to be already stripped of leading/trailing
    whitespace and to not include an explicit scheme (e.g., "http://").

    Args:
        host_address: The host address string to normalize.
        Expected format: "host", "host:port", "[ipv6]", "[ipv6]:port".

    Returns:
        The normalized host string (e.g., "192.168.1.100", "[::1]", "example.com:8080"), with
        IPv6 addresses bracketed if necessary, and the port appended if present.

    Raises:
        ValueError: If the host address is invalid or cannot be parsed into a valid
            hostname.
    """
    if not host_address:
        raise ValueError("Host address cannot be empty.")

    # urlparse needs a scheme to correctly parse the netloc.
    # Prepend a dummy scheme. This works even if host_address is already bracketed IPv6 with port.
    parsed = urlparse(f"scheme://{host_address}")  # Using "scheme" as a generic dummy

    host = parsed.hostname  # Extracts hostname, unbrackets IPv6
    port = parsed.port

    if not host:
        # This can happen if host_address is malformed, e.g., just ":8080"
        raise ValueError(
            f"Invalid host address format: '{host_address}'. Could not extract hostname."
        )

    # Validate/format the host part
    try:
        ip = ipaddress.ip_address(
            host
        )  # Will raise ValueError if host is not a valid IP string
        host_part_normalized = f"[{host}]" if ip.version == 6 else host
    except ValueError:
        # Not an IP address, assume it's a valid hostname.
        # No further normalization needed for hostnames here.
        host_part_normalized = host

    return f"{host_part_normalized}:{port}" if port else host_part_normalized


def prepare_base_url(host_input_original_raw: str) -> str | None:
    """
    Prepare and validate the base URL from the host input.
    Handles scheme prepending and IPv6 normalization.

    Args:
        host_input_original_raw: The raw host input string from configuration.

    Returns: The prepared base URL string (e.g., "http://192.168.1.100"),
             or None if the input is invalid or cannot be processed.
    """
    host_input_original = host_input_original_raw.strip()
    host_to_process = host_input_original
    scheme_provided = host_to_process.lower().startswith(("http://", "https://"))
    current_scheme = ""

    if scheme_provided:
        parsed_for_scheme = urlparse(host_to_process)
        current_scheme = parsed_for_scheme.scheme
        host_to_process = parsed_for_scheme.netloc  # This is the part to normalize
        if not host_to_process:  # e.g. "http://"
            _LOGGER.error(
                f"Invalid host/IP '{host_input_original_raw}'. Contains scheme but empty host part."
            )
            return None
    # If no scheme provided, host_to_process remains the original input.
    # normalize_host_for_scheme expects something like "host" or "host:port" or "[ipv6]:port"
    try:
        normalized_host = normalize_host_for_scheme(host_to_process)
    except ValueError as e:
        _LOGGER.error(
            f"Invalid host/IP format '{host_input_original_raw}' for HDG Boiler. "
            f"Normalization of host part '{host_to_process}' failed: {e}. Please check configuration."
        )
        return None
    schemed_host_input = f"{current_scheme or 'http'}://{normalized_host}"  # Default to http if no scheme was present

    parsed_url = urlparse(schemed_host_input)
    # Final check after potential normalization and scheme prepending
    if not parsed_url.netloc:
        _LOGGER.error(
            f"Invalid host/IP '{host_input_original}'. Empty netloc after processing to '{schemed_host_input}'."
        )
        return None

    return urlunparse((parsed_url.scheme, parsed_url.netloc, "", "", "", ""))


def _get_locale_separators_from_known_list(
    locale_str: str,
) -> tuple[str, str] | None:
    """
    Retrieve decimal and thousands separators for a given locale from a predefined list.

    Args:
        locale_str: The locale string (e.g., 'en_US', 'de_DE').

    Returns: A tuple containing the decimal point and thousands separator for the locale,
             or None if the locale is not in the predefined list.
    """
    if locale_str in KNOWN_LOCALE_SEPARATORS:
        conv = KNOWN_LOCALE_SEPARATORS[locale_str]
        return conv["decimal_point"], conv["thousands_sep"]
    return None


def _normalize_string_by_locale(
    value_str: str, locale_str: str, log_prefix: str, raw_cleaned_value_for_log: str
) -> str | None:
    """
    Normalize a string using locale-specific decimal and thousands separators.
    Uses a predefined list of known locales and their separators.

    Args:
        value_str: The string to normalize.
        locale_str: The locale string (e.g., 'en_US', 'de_DE').
        log_prefix: A prefix string for log messages, providing context.
        raw_cleaned_value_for_log: Original cleaned value for logging.

    Returns:
        The string normalized according to the locale's separators, or None if the locale is not known.
    """
    normalized_value = value_str

    if separators := _get_locale_separators_from_known_list(locale_str):
        decimal_sep, thousands_sep = separators
        if (
            thousands_sep
        ):  # Only replace if a thousands separator is defined for the locale
            normalized_value = normalized_value.replace(thousands_sep, "")
        if (
            decimal_sep and decimal_sep != "."
        ):  # Only replace if decimal is not already '.'
            normalized_value = normalized_value.replace(decimal_sep, ".")
        _LOGGER.debug(
            f"{log_prefix}Normalized '{raw_cleaned_value_for_log}' to '{normalized_value}' "
            f"using pre-defined locale '{locale_str}' (dec: '{decimal_sep}', thou: '{thousands_sep}')"
        )
        return normalized_value
    else:
        _LOGGER.warning(
            f"{log_prefix}Locale '{locale_str}' not in pre-defined list for numeric parsing. "
            "Falling back to heuristic. Consider adding this locale to KNOWN_LOCALE_SEPARATORS if it's common."
        )
        return None  # Indicate failure to normalize by locale, allowing fallback


def _normalize_string_by_heuristic(
    value_str: str, log_prefix: str, raw_cleaned_value_for_log: str
) -> str | None:
    """
    Normalize a string using a heuristic for mixed decimal/thousands separators.

    Args:
        value_str: The string to normalize.
        log_prefix: A prefix string for log messages, providing context.
        raw_cleaned_value_for_log: Original cleaned value for logging.

    Returns:
        The string with heuristically normalized separators, or None if the format is ambiguous.
    """
    # First, remove any spaces or non-breaking spaces that might be used as thousands separators.
    if " " in value_str or "\u00a0" in value_str:
        original_for_space_log = value_str
        value_str = value_str.replace(" ", "").replace("\u00a0", "")
        _LOGGER.debug(
            f"{log_prefix}Heuristic: removed spaces/NBSPs from '{original_for_space_log}', now '{value_str}'."
        )

    if "." in value_str and "," in value_str:
        last_dot_pos = value_str.rfind(".")
        last_comma_pos = value_str.rfind(",")
        if last_comma_pos > last_dot_pos:  # European "1.234,56"
            normalized_str = value_str.replace(".", "").replace(",", ".")
            _LOGGER.debug(
                f"{log_prefix}Heuristic: mixed separators in '{value_str}', assuming European, normalized to '{normalized_str}'."
            )
            return normalized_str
        elif last_dot_pos > last_comma_pos:  # US "1,234.56"
            normalized_str = value_str.replace(",", "")
            _LOGGER.debug(
                f"{log_prefix}Heuristic: mixed separators in '{value_str}', assuming US, normalized to '{normalized_str}'."
            )
            return normalized_str
        _LOGGER.warning(
            f"{log_prefix}Heuristic: Ambiguous mixed separators in '{value_str}'. Unable to normalize reliably."
        )
        return None
    elif "," in value_str:  # Only comma present
        normalized_str = value_str.replace(",", ".")
        _LOGGER.debug(
            f"{log_prefix}Heuristic: replaced comma with dot in '{raw_cleaned_value_for_log}', now '{normalized_str}'."
        )
        return normalized_str
    return (
        value_str  # No heuristic normalization needed if only one or no separator type
    )


def extract_numeric_string(
    raw_cleaned_value: str,
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
    locale: str | None = None,
) -> str | None:
    """
    Extract the numeric part of a string using regex after locale-aware normalization.

    This function first attempts to normalize the input string to use '.' as the
    decimal separator. This normalization can be guided by an optional `locale`
    parameter. If no locale is provided or if locale-specific normalization fails,
    a heuristic is applied which also handles removal of spaces and non-breaking
    spaces used as thousands separators. After normalization, `NUMERIC_PART_REGEX`
    is used to find the first float-like number, ignoring any trailing units or
    non-numeric characters.

    Args:
        raw_cleaned_value: The already whitespace-cleaned string to parse.
        node_id_for_log: Optional HDG node ID for logging context.
        entity_id_for_log: Optional entity ID for logging context.
        locale: Optional locale string (e.g., 'en_US', 'de_DE') to guide
                separator normalization. If None, a heuristic is applied.

    Returns:
        The extracted numeric string, or None if not found.
    """
    value_str = (
        raw_cleaned_value  # Assumes raw_cleaned_value is already stripped by caller.
    )

    log_prefix = ""
    if node_id_for_log and entity_id_for_log:
        log_prefix = f"Node {node_id_for_log} ({entity_id_for_log}): "
    elif node_id_for_log:
        log_prefix = f"Node {node_id_for_log}: "
    elif entity_id_for_log:
        log_prefix = f"Entity {entity_id_for_log}: "

    normalized_value_str: str | None = None

    if locale:
        normalized_value_str = _normalize_string_by_locale(
            value_str, locale, log_prefix, raw_cleaned_value
        )
        # If locale normalization failed (returned None), fall through to heuristic
        if normalized_value_str is None:
            _LOGGER.debug(
                f"{log_prefix}Locale normalization failed for '{raw_cleaned_value}', attempting heuristic."
            )
            normalized_value_str = _normalize_string_by_heuristic(
                value_str, log_prefix, raw_cleaned_value
            )
    else:  # No locale provided, use heuristic directly
        normalized_value_str = _normalize_string_by_heuristic(
            value_str, log_prefix, raw_cleaned_value
        )

    if normalized_value_str is None:  # If all normalization attempts failed
        return None

    if match := NUMERIC_PART_REGEX.search(normalized_value_str):
        return match.group(0)
    _LOGGER.debug(
        f"{log_prefix}No numeric part found in '{normalized_value_str}' (original: '{raw_cleaned_value}') during numeric extraction."
    )
    return None


def parse_percent_from_string(
    cleaned_value: str,
    regex_pattern: str = DEFAULT_PERCENT_REGEX_PATTERN,
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
) -> int | None:
    """
    Parse percentage from a string using a regex pattern.

    Args:
        cleaned_value: The whitespace-cleaned string to parse.
        regex_pattern: The regex pattern to use for extraction.
                       Defaults to `DEFAULT_PERCENT_REGEX_PATTERN`.
        node_id_for_log: Optional HDG node ID for logging context.
        entity_id_for_log: Optional entity ID for logging context.
    Returns:
        The extracted integer percentage, or None if not found or if a parsing error occurs.
    """
    log_prefix = (
        f"Node {node_id_for_log} ({entity_id_for_log}): "
        if node_id_for_log and entity_id_for_log
        else ""
    )
    if match := re.search(regex_pattern, cleaned_value):
        if (
            match.lastindex is not None and match.lastindex >= 1
        ):  # Check if group 1 exists
            try:
                return int(match[1])
            except ValueError:
                _LOGGER.warning(
                    f"{log_prefix}Could not parse numeric part from regex group 1 ('{match[1]}') in '{cleaned_value}' for percent regex."
                )
                return None
            except (
                IndexError
            ):  # Should be caught by lastindex check, but as a safeguard
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
    """
    Format a numeric value into the string representation expected by the HDG API.

    Args:
        numeric_value: The numeric value (int or float) to format.
        setter_type: The 'setter_type' string from SENSOR_DEFINITIONS (e.g., "int", "float1", "float2").

    Returns:
        The formatted string suitable for the HDG API.

    Raises:
        ValueError: If the `setter_type` is unknown or if the `numeric_value`
                    cannot be formatted according to the specified type.
    """
    if setter_type == "int":
        # Ensure it's treated as an integer, handle potential float input like 10.0
        return str(int(round(numeric_value)))
    elif setter_type == "float1":
        return f"{numeric_value:.1f}"
    elif setter_type == "float2":
        return f"{numeric_value:.2f}"
    else:
        msg = f"Unknown 'setter_type' ('{setter_type}') encountered during API value formatting for value '{numeric_value}'."
        _LOGGER.error(msg)
        raise ValueError(
            msg
        )  # Use ValueError as it's a data/config issue, not API communication.


def coerce_and_round_float(
    value_to_set: Any, precision: int, node_type_str: str
) -> tuple[float | None, bool, str]:
    """
    Coerce an input value to a float and round it to a specified precision.
    Typically used for 'float1' or 'float2' setter types.

    Args:
        value_to_set: The value to coerce and round.
        precision: The number of decimal places to round to.
        node_type_str: A string representation of the node type, used in error messages.

    Returns:
        A tuple containing (rounded_float_or_None, success_flag, error_message_string).
    """
    try:
        return round(float(value_to_set), precision), True, ""
    except (ValueError, TypeError):
        return (
            None,
            False,
            f"Value '{value_to_set}' not parsable as float for {node_type_str}.",
        )


def extract_base_node_id(node_id_from_def: str) -> str:
    """
    Extract the base numeric ID from an 'hdg_node_id' string from SENSOR_DEFINITIONS.
    Removes known trailing setter suffixes (T, U, V, W, X, Y, case-insensitive).

    Args:
        node_id_from_def: The node ID string from SENSOR_DEFINITIONS.
    Returns:
        The base numeric part of the node ID, or the original string if no known
        suffix is matched or if the format is unexpected.
    """
    if not node_id_from_def:
        return node_id_from_def
    if match := re.match(r"^(\d+)[TUVWXYtuvwxy]?$", node_id_from_def):
        return match[1]
    _LOGGER.warning(
        "extract_base_node_id: Unexpected node_id format '%s' (did not match expected numeric base with optional suffix). Returning original value.",
        node_id_from_def,
    )
    return node_id_from_def


def safe_float_convert(
    val_to_convert: Any, val_name: str, entity_name_for_log: str | None = None
) -> tuple[bool, float | None, str]:
    """
    Safely convert a value (typically from SENSOR_DEFINITIONS min/max/step) to float.

    Args:
        val_to_convert: The value to convert.
        val_name: Name of the value being converted (for logging, e.g., "setter_min_val").
        entity_name_for_log: Optional entity name for logging context.

    Returns:
        A tuple: (success_flag, converted_float_or_None, error_message_string).
    """
    log_prefix = f"Entity '{entity_name_for_log}': " if entity_name_for_log else ""
    if val_to_convert is None:
        _LOGGER.error(f"{log_prefix}Config error: {val_name} is None.")
        return False, None, f"Config error: {val_name} is None."
    try:
        return True, float(val_to_convert), ""
    except (ValueError, TypeError) as e:
        _LOGGER.error(
            f"{log_prefix}Config error: {val_name} '{val_to_convert}' not valid number: {e}"
        )
        return (
            False,
            None,
            f"Config error: {val_name} '{val_to_convert}' not valid number.",
        )


def normalize_alias_for_comparison(alias: str) -> str:
    """
    Normalize an alias string for case-insensitive comparison.
    Converts to lowercase and strips leading/trailing standard whitespace.

    Args:
        alias: The alias string to normalize.

    Returns:
        The normalized alias string.
    """
    return alias.strip().lower() if isinstance(alias, str) else ""


def normalize_unique_id_component(component: str) -> str:
    """
    URL-safe encode a component string for use in unique IDs.
    Ensures that the component is safe for use in contexts where special
    characters (like ':', '/', etc.) might be problematic.

    Args:
        component: The string component to normalize.

    Returns:
        The URL-safe encoded string.
    """
    return quote(component, safe="")


def parse_int_from_string(
    raw_value: str,
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
) -> int | None:
    """
    Parse an integer from a string, robustly handling potential float representations (e.g., "10.0").

    This function first extracts a numeric string part (which might be a float)
    using `extract_numeric_string`, then converts it to a float, and finally to an integer.

    Args:
        raw_value: The string to parse.
        node_id_for_log: Optional HDG node ID for logging context.
        entity_id_for_log: Optional entity ID for logging context.
    """
    numeric_part_str = extract_numeric_string(
        raw_value, node_id_for_log, entity_id_for_log
    )
    if numeric_part_str is None:
        return None
    try:
        return int(float(numeric_part_str))
    except ValueError:
        log_prefix = ""
        if node_id_for_log and entity_id_for_log:
            log_prefix = f"Node {node_id_for_log} ({entity_id_for_log}): "
        elif node_id_for_log:
            log_prefix = f"Node {node_id_for_log}: "
        elif entity_id_for_log:
            log_prefix = f"Entity {entity_id_for_log}: "
        _LOGGER.warning(
            f"{log_prefix}Could not parse int value from '{numeric_part_str}' (original: '{raw_value}')."
        )
        return None


def parse_float_from_string(
    raw_value: str,
    node_id_for_log: str | None = None,
    entity_id_for_log: str | None = None,
) -> float | None:
    """
    Parse a float from a string, extracting the numeric part first.

    Args:
        raw_value: The string to parse.
        node_id_for_log: Optional HDG node ID for logging context.
        entity_id_for_log: Optional entity ID for logging context.

    """
    numeric_part_str = extract_numeric_string(
        raw_value, node_id_for_log, entity_id_for_log
    )
    if numeric_part_str is None:
        return None
    try:
        return float(numeric_part_str)
    except ValueError:
        log_prefix = ""
        if node_id_for_log and entity_id_for_log:
            log_prefix = f"Node {node_id_for_log} ({entity_id_for_log}): "
        elif node_id_for_log:
            log_prefix = f"Node {node_id_for_log}: "
        elif entity_id_for_log:
            log_prefix = f"Entity {entity_id_for_log}: "
        _LOGGER.warning(
            f"{log_prefix}Could not parse float value from '{numeric_part_str}' (original: '{raw_value}')."
        )
        return None
