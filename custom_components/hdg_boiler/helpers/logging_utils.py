"""
Logging utility functions for the HDG Bavaria Boiler integration.

This module provides simple helper functions to create standardized log message
prefixes, incorporating node ID and/or entity ID for consistent and traceable logging.
"""

from __future__ import annotations

__version__ = "0.1.1"

# No external imports needed for this simple utility.
# No DOMAIN or _LOGGER needed here as it's a pure string formatting utility.


def make_log_prefix(
    node_id_for_log: str | None = None, entity_id_for_log: str | None = None
) -> str:
    """
    Generate a standardized log prefix string based on node_id and/or entity_id.

    Args:
        node_id_for_log: The HDG node ID to include in the prefix.
        entity_id_for_log: The Home Assistant entity ID to include in the prefix.

    Returns:
        A formatted string prefix for log messages, e.g., "Node 1234 (sensor.my_sensor): ",
        "Node 1234: ", or "Entity sensor.my_sensor: ".
    """
    if node_id_for_log:
        if entity_id_for_log:
            return f"Node {node_id_for_log} ({entity_id_for_log}): "
        return f"Node {node_id_for_log}: "
    return f"Entity {entity_id_for_log}: " if entity_id_for_log else ""
