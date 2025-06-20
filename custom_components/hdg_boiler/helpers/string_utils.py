"""
String manipulation utility functions for the HDG Bavaria Boiler integration.

This module provides helper functions for common string operations such as
stripping suffixes from HDG API node IDs, extracting base node IDs, and
normalizing strings for comparison or use in unique identifiers.
"""

from __future__ import annotations

__version__ = "0.1.1"

import logging
import re
from urllib.parse import quote

from ..const import DOMAIN, KNOWN_HDG_API_SETTER_SUFFIXES

_LOGGER = logging.getLogger(DOMAIN)


def strip_hdg_node_suffix(node_id_with_suffix: str) -> str:
    """
    Remove a known HDG API setter suffix (T, U, V, W, X, Y, case-insensitive) if present.

    Args:
        node_id_with_suffix: The node ID string which might have a suffix.

    Returns:
        The node ID string with the suffix removed, or the original string if no known suffix was found.
    """
    if (
        node_id_with_suffix
        and node_id_with_suffix[-1].upper() in KNOWN_HDG_API_SETTER_SUFFIXES
    ):
        return node_id_with_suffix[:-1]
    return node_id_with_suffix


def extract_base_node_id(node_id_from_def: str) -> str:
    """
    Extract the base numeric ID from an 'hdg_node_id' string, typically from SENSOR_DEFINITIONS.

    This function attempts to isolate the numeric part of a node ID string that might
    include a trailing character (e.g., 'T', 'U') indicating its type or settability.

    Args:
        node_id_from_def: The node ID string as defined (e.g., "1234T", "5678").

    Returns: The extracted base numeric ID (e.g., "1234", "5678"), or the original string if the format is unexpected.
    """
    if not node_id_from_def:
        return node_id_from_def
    if match := re.match(r"^(\d+)[TUVWXYtuvwxy]?$", node_id_from_def):
        return match[1]
    _LOGGER.warning(
        "extract_base_node_id: Unexpected node_id format '%s'. Returning original.",
        node_id_from_def,
    )
    return node_id_from_def


def normalize_alias_for_comparison(alias: str) -> str:
    """
    Normalize an alias string for case-insensitive comparison by stripping whitespace and converting to lowercase.

    Args:
        alias: The alias string to normalize.

    Returns:
        The normalized alias string, or an empty string if the input was not a string or was None.
    """
    return alias.strip().lower() if isinstance(alias, str) else ""


def normalize_unique_id_component(component: str) -> str:
    """
    URL-safe encode a component string for robust use in unique IDs.

    Args:
        component: The string component to normalize.

    Returns:
        A URL-safe encoded version of the component string.
    """
    return quote(component, safe="")
