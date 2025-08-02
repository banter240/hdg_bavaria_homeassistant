"""String manipulation utility functions for the HDG Bavaria Boiler integration.

This module provides helper functions for common string operations such as
stripping suffixes from HDG API node IDs, extracting base node IDs, and
normalizing strings for comparison or use in unique identifiers.
"""

from __future__ import annotations

__version__ = "0.2.0"

import logging
import re
from urllib.parse import quote

from ..const import DOMAIN, KNOWN_HDG_API_SETTER_SUFFIXES

_LOGGER = logging.getLogger(DOMAIN)

__all__ = [
    "strip_hdg_node_suffix",
    "normalize_alias_for_comparison",
    "normalize_unique_id_component",
]

# Pre-compile the regex for stripping suffixes for efficiency.
# This regex ensures we only strip a known suffix if the preceding part is numeric.
_SUFFIX_PATTERN = re.compile(
    rf"^(\d+)[{''.join(KNOWN_HDG_API_SETTER_SUFFIXES)}]?$", re.IGNORECASE
)


def strip_hdg_node_suffix(node_id_from_def: str) -> str:
    """Extract the base numeric ID from a node ID string by stripping a known suffix.

    This function robustly isolates the numeric part of a node ID string (e.g., "22003T")
    by matching a leading numeric sequence followed by an optional known suffix.

    Args:
        node_id_from_def: The node ID string as defined (e.g., "22003T", "4050").

    Returns:
        The extracted base numeric ID (e.g., "22003", "4050"), or the original string
        if the format is unexpected.

    """
    if not node_id_from_def:
        return ""

    if match := _SUFFIX_PATTERN.match(node_id_from_def):
        return match[1]

    _LOGGER.debug(
        "strip_hdg_node_suffix: Unexpected node_id format '%s'. Returning original.",
        node_id_from_def,
    )
    return node_id_from_def


def normalize_alias_for_comparison(alias: str) -> str:
    """Normalize an alias for case-insensitive comparison.

    Strips whitespace and converts to lowercase.

    Args:
        alias: The alias string to normalize.

    Returns:
        The normalized alias string, or an empty string if input is invalid.

    """
    return alias.strip().lower() if isinstance(alias, str) else ""


def normalize_unique_id_component(component: str) -> str:
    """URL-safe encode a component for robust use in unique IDs.

    Args:
        component: The string component to normalize.

    Returns:
        A URL-safe encoded version of the component string.

    """
    return quote(component, safe="")
