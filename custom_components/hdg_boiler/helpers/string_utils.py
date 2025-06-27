"""String manipulation utility functions for the HDG Bavaria Boiler integration.

This module provides helper functions for common string operations such as
stripping suffixes from HDG API node IDs, extracting base node IDs, and
normalizing strings for comparison or use in unique identifiers.
"""

from __future__ import annotations

__version__ = "0.1.1"

import logging
import re
from urllib.parse import quote

from ..const import DOMAIN

_LOGGER = logging.getLogger(DOMAIN)


def strip_hdg_node_suffix(node_id_from_def: str) -> str:
    """Extract the base numeric ID from a node ID string by stripping a known suffix.

    This function robustly isolates the numeric part of a node ID string (e.g., "22003T")
    by matching a leading numeric sequence followed by an optional known suffix
    (from KNOWN_HDG_API_SETTER_SUFFIXES). This prevents incorrect stripping from
    non-numeric node IDs.

    Args:
        node_id_from_def: The node ID string as defined (e.g., "22003T", "4050").

    Returns:
        The extracted base numeric ID (e.g., "22003", "4050"), or the original string
        if the format is unexpected.

    """
    if not node_id_from_def:
        return node_id_from_def
    # This regex ensures we only strip a suffix if the preceding part is numeric.
    if match := re.match(r"^(\d+)[TUVWXY]?$", node_id_from_def, re.IGNORECASE):
        return match[1]
    _LOGGER.warning(
        "strip_hdg_node_suffix: Unexpected node_id format '%s'. Returning original.",
        node_id_from_def,
    )
    return node_id_from_def


def normalize_alias_for_comparison(alias: str) -> str:
    """Normalize an alias string for case-insensitive comparison by stripping whitespace and converting to lowercase.

    Args:
        alias: The alias string to normalize.

    Returns:
        The normalized alias string, or an empty string if the input was not a string or was None.

    """
    return alias.strip().lower() if isinstance(alias, str) else ""


def normalize_unique_id_component(component: str) -> str:
    """URL-safe encode a component string for robust use in unique IDs.

    Args:
        component: The string component to normalize.

    Returns:
        A URL-safe encoded version of the component string.

    """
    return quote(component, safe="")
