"""
Utility functions for the HDG Bavaria Boiler integration.

This module contains helper functions used across different parts of the integration,
such as node ID manipulation and URL normalization.
"""

from __future__ import annotations

__version__ = "0.6.10"

import logging
import re
import unicodedata
import ipaddress
from urllib.parse import urlparse, urlunparse, quote, splitport
from typing import Final, Optional, Tuple, Any, Dict
from .const import DOMAIN


_LOGGER = logging.getLogger(DOMAIN)
# Known HDG API setter suffixes (TUVWXY), case-insensitive.
KNOWN_HDG_API_SETTER_SUFFIXES: Final = "TUVWXY"

# Pre-compiled regex for efficiently extracting numeric parts from strings.
NUMERIC_PART_REGEX: Final = re.compile(r"([-+]?\d*\.?\d+)")
# Default regex pattern for percent parsing (German output "X %-Schritte").
DEFAULT_PERCENT_REGEX_PATTERN: Final = r"(\d+)\s*%-Schritte"

# Predefined locale separators to avoid global pylocale.setlocale
KNOWN_LOCALE_SEPARATORS: Final[Dict[str, Dict[str, str]]] = {
    "en_US": {"decimal_point": ".", "thousands_sep": ","},
    "de_DE": {"decimal_point": ",", "thousands_sep": "."},
    "en_GB": {"decimal_point": ".", "thousands_sep": ","},
    "fr_FR": {"decimal_point": ",", "thousands_sep": " "},  # NBSP often, but space is common
    "it_IT": {"decimal_point": ",", "thousands_sep": "."},
    "es_ES": {"decimal_point": ",", "thousands_sep": "."},
}


def strip_hdg_node_suffix(node_id_with_suffix: str) -> str:
    """
    Remove known HDG API setter suffix (TUVWXY, case-insensitive) if present.

    Returns:
        The base node ID (numeric part if suffix was present, else original string).
    """
    if node_id_with_suffix and node_id_with_suffix[-1].upper() in KNOWN_HDG_API_SETTER_SUFFIXES:
        return node_id_with_suffix[:-1]
    return node_id_with_suffix


def normalize_host_for_scheme(host_address: str) -> str:
    """
    Normalize a host address string, particularly for IPv6 addresses.
    Uses ipaddress and urllib.parse.splitport to robustly handle IPv4,
    IPv6 (with or without brackets), and optional ports.
    Input 'host_address' is assumed to be already stripped of leading/trailing
    whitespace and without an explicit scheme (e.g., "http://").

    Raises:
        ValueError: If an IPv6 address with a port is missing brackets.

    Args:
        host_address: The host address string to normalize.

    Returns:
        The normalized host string, with IPv6 addresses bracketed if necessary,
        and port appended if present, or the original address if parsing fails.
    """
    # Heuristic check for malformed IPv6 with port (e.g., "2001:db8::1:8080" instead of "[2001:db8::1]:8080")
    # Valid IPv6 with port: "[2001:db8::1]:8080"
    # Invalid: "2001:db8::1:8080" (ambiguous)
    if ":" in host_address and not host_address.startswith("["):
        try:
            potential_host, potential_port = splitport(host_address)
            if potential_port and potential_host and ":" in potential_host:
                # Check if the host part is indeed a valid IPv6 address
                ipaddress.ip_address(potential_host)
                # If we reach here, it's a valid IPv6 address, a port was found,
                # but the original string was not bracketed. This is the malformed case.
                raise ValueError(
                    f"Malformed IPv6 address with port (missing brackets): '{host_address}'. "
                    "IPv6 addresses with ports must be enclosed in brackets, e.g. '[2001:db8::1]:8080'"
                )
        except ValueError as e:
            if "Malformed IPv6 address with port" in str(e):  # Propagate our specific error
                raise
            # Otherwise, potential_host was not a valid IPv6, or splitport failed.
            # This is not the specific malformation we're checking for here, so we continue.
            _LOGGER.debug(
                f"Pre-check for malformed IPv6 with port for '{host_address}' did not confirm specific error: {e}"
            )
        except Exception as e_generic:  # Catch any other unexpected errors during this check
            _LOGGER.debug(
                f"Unexpected error during pre-check for malformed IPv6 for '{host_address}': {e_generic}"
            )

    # Split out port if present
    host, port_str = splitport(host_address)
    if host is None:  # Should not happen if host_address is not empty
        _LOGGER.warning(
            f"Could not parse hostname from '{host_address}' using splitport. Returning original."
        )
        return host_address

    # Remove brackets if present (e.g., "[::1]")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]

    # Check if host is a valid IPv6 address
    is_ipv6 = False
    try:
        # Ensure host is not empty before passing to ip_address, as ip_address("") raises ValueError
        if host:
            ip = ipaddress.ip_address(host)
            is_ipv6 = ip.version == 6
    except ValueError:
        # Not a valid IP address (could be a hostname or invalid IP string)
        is_ipv6 = False  # Treat as not IPv6 for bracketing purposes

    # Re-bracket if IPv6
    if is_ipv6:
        host = f"[{host}]"

    return f"{host}:{port_str}" if port_str else host


def prepare_base_url(host_input_original_raw: str) -> Optional[str]:
    """
    Prepare and validate the base URL from the host input.
    Handles scheme prepending and IPv6 normalization.

    Args:
        host_input_original_raw: The raw host input string from configuration.

    Returns:
        The prepared base URL string (e.g., "http://192.168.1.100"), or None if invalid.
    """
    host_input_original = host_input_original_raw.strip()
    host_to_process = host_input_original

    if not host_to_process.lower().startswith(("http://", "https://")):
        normalized_host = normalize_host_for_scheme(host_to_process)
        schemed_host_input = f"http://{normalized_host}"
    else:
        schemed_host_input = host_to_process

    parsed_url = urlparse(schemed_host_input)
    if not parsed_url.netloc:
        _LOGGER.error(
            f"Invalid host/IP '{host_input_original}'. Empty netloc after processing to '{schemed_host_input}'."
        )
        return None

    return urlunparse((parsed_url.scheme, parsed_url.netloc, "", "", "", ""))


def _get_locale_separators_from_known_list(
    locale_str: str,
) -> Optional[Tuple[str, str]]:
    """Retrieve decimal and thousands separators for a given locale from a predefined list."""
    if locale_str in KNOWN_LOCALE_SEPARATORS:
        conv = KNOWN_LOCALE_SEPARATORS[locale_str]
        return conv["decimal_point"], conv["thousands_sep"]
    return None


def _normalize_string_by_locale(
    value_str: str, locale_str: str, log_prefix: str, raw_cleaned_value_for_log: str
) -> Optional[str]:
    """
    Normalize a string using locale-specific decimal and thousands separators.
    Uses a predefined list of known locales and their separators.

    Args:
        value_str: The string to normalize.
        locale_str: The locale string (e.g., 'en_US', 'de_DE').
        log_prefix: Prefix for log messages.
        raw_cleaned_value_for_log: Original cleaned value for logging.

    Returns:
        The normalized string, or None if locale processing fails critically.
    """
    normalized_value = value_str

    separators = _get_locale_separators_from_known_list(locale_str)

    if separators:
        decimal_sep, thousands_sep = separators
        if thousands_sep:  # Only replace if a thousands separator is defined for the locale
            normalized_value = normalized_value.replace(thousands_sep, "")
        if decimal_sep and decimal_sep != ".":  # Only replace if decimal is not already '.'
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
) -> Optional[str]:
    """
    Normalize a string using a heuristic for mixed decimal/thousands separators.

    Args:
        value_str: The string to normalize.
        log_prefix: Prefix for log messages.
        raw_cleaned_value_for_log: Original cleaned value for logging.

    Returns:
        The normalized string, or None if ambiguous.
    """
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
    return value_str  # No heuristic normalization needed if only one or no separator type


def extract_numeric_string(
    raw_cleaned_value: str,
    node_id_for_log: Optional[str] = None,
    entity_id_for_log: Optional[str] = None,
    locale: Optional[str] = None,
) -> Optional[str]:
    """
    Helper to extract numeric string part using regex after locale-aware normalization.
    NUMERIC_PART_REGEX finds the first float-like number, ignoring trailing units.
    Handles mixed decimal/thousands separators (e.g., "1.234,56" or "1,234.56").

    Ambiguous handling: If `locale` is not provided and both '.' and ',' are present,
    the function currently relies on the position of the last separator to determine
    the decimal separator, which may misinterpret ambiguous or malformed input.
    To reduce risk, you can specify the `locale` parameter (e.g., 'en_US', 'de_DE')
    to explicitly set decimal and thousands separators.

    Args:
        raw_cleaned_value: The already whitespace-cleaned string to parse.
        node_id_for_log: Optional HDG node ID for logging context.
        entity_id_for_log: Optional entity ID for logging context.
        locale: Optional locale string (e.g., 'en_US', 'de_DE') to guide
                decimal/thousands separator normalization. If None, a heuristic is used.


    Returns:
        The extracted numeric string, or None if not found.
    """
    value_str = raw_cleaned_value  # Assumes raw_cleaned_value is already stripped by caller.

    log_prefix = ""
    if node_id_for_log and entity_id_for_log:
        log_prefix = f"Node {node_id_for_log} ({entity_id_for_log}): "
    elif node_id_for_log:
        log_prefix = f"Node {node_id_for_log}: "
    elif entity_id_for_log:
        log_prefix = f"Entity {entity_id_for_log}: "

    normalized_value_str: Optional[str] = None

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
    node_id_for_log: Optional[str] = None,
    entity_id_for_log: Optional[str] = None,
) -> Optional[int]:
    """
    Parse percentage from a string using a regex pattern.

    Args:
        cleaned_value: The whitespace-cleaned string to parse.
        regex_pattern: The regex pattern to use for extraction. Defaults to DEFAULT_PERCENT_REGEX_PATTERN.
        node_id_for_log: Optional HDG node ID for logging context.
        entity_id_for_log: Optional entity ID for logging context.
    Returns:
        The extracted integer percentage, or None if not found or parse error.
    """
    log_prefix = (
        f"Node {node_id_for_log} ({entity_id_for_log}): "
        if node_id_for_log and entity_id_for_log
        else ""
    )
    if match := re.search(regex_pattern, cleaned_value):
        if match.lastindex is not None and match.lastindex >= 1:  # Check if group 1 exists
            try:
                return int(match[1])
            except ValueError:
                _LOGGER.warning(
                    f"{log_prefix}Could not parse numeric part from regex group 1 ('{match[1]}') in '{cleaned_value}' for percent regex."
                )
                return None
            except IndexError:  # Should be caught by lastindex check, but as a safeguard
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


def coerce_and_round_float(
    value_to_set: Any, precision: int, node_type_str: str
) -> Tuple[Optional[float], bool, str]:
    """
    Coerce input to float and round. Used for 'float1'/'float2' types.

    Args:
        value_to_set: The value to coerce and round.
        precision: The number of decimal places to round to.
        node_type_str: String representation of the node type for error messages.

    Returns:
        A tuple: (rounded_float_or_None, success_flag, error_message_string).
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
    Extract base numeric ID from an 'hdg_node_id' string.
    Removes known trailing setter suffixes (TUVWXY, case-insensitive).

    Args:
        node_id_from_def: The node ID string from SENSOR_DEFINITIONS.
    Returns:
        The base numeric part of the node ID, or the original string if no suffix is matched.
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
    val_to_convert: Any, val_name: str, entity_name_for_log: Optional[str] = None
) -> Tuple[bool, Optional[float], str]:
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
        return False, None, f"Config error: {val_name} '{val_to_convert}' not valid number."


def normalize_alias_for_comparison(alias: str) -> str:
    """
    Normalize an alias string for case-insensitive and Unicode-aware comparison.

    Converts to lowercase and applies NFC Unicode normalization.

    Args:
        alias: The alias string to normalize.
    Returns:
        The normalized alias string.
    """
    return unicodedata.normalize("NFC", alias).lower()


def normalize_unique_id_component(component: str) -> str:
    """
    URL-safe encode a component string for use in unique IDs.
    Ensures that the component is safe for use in contexts where special characters might be problematic.

    Args:
        component: The string component to normalize.

    Returns:
        The URL-safe encoded string.
    """
    return quote(component, safe="")


def parse_int_from_string(
    raw_value: str,
    node_id_for_log: Optional[str] = None,
    entity_id_for_log: Optional[str] = None,
) -> Optional[int]:
    """
    Parse an integer from a string, robustly handling potential float representations.
    Uses extract_numeric_string to get the numeric part first.
    """
    numeric_part_str = extract_numeric_string(raw_value, node_id_for_log, entity_id_for_log)
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
    node_id_for_log: Optional[str] = None,
    entity_id_for_log: Optional[str] = None,
) -> Optional[float]:
    """
    Parse a float from a string.
    Uses extract_numeric_string to get the numeric part first.
    """
    numeric_part_str = extract_numeric_string(raw_value, node_id_for_log, entity_id_for_log)
    if numeric_part_str is None:
        return None
    try:
        return float(numeric_part_str)
    except ValueError:
        log_prefix = ""
        if node_id_for_log and entity_id_for_log:  # pragma: no cover
            log_prefix = f"Node {node_id_for_log} ({entity_id_for_log}): "  # pragma: no cover
        elif node_id_for_log:  # pragma: no cover
            log_prefix = f"Node {node_id_for_log}: "  # pragma: no cover
        elif entity_id_for_log:  # pragma: no cover
            log_prefix = f"Entity {entity_id_for_log}: "  # pragma: no cover
        _LOGGER.warning(
            f"{log_prefix}Could not parse float value from '{numeric_part_str}' (original: '{raw_value}')."
        )
        return None
