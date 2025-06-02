"""
Manages the dynamic creation of polling group structures from entity definitions.

This module contains the logic to read the `SENSOR_DEFINITIONS` from
`definitions.py` and dynamically build the `HDG_NODE_PAYLOADS` and
`POLLING_GROUP_ORDER` structures required by the data update coordinator.
This centralizes the definition of nodes and their polling groups in
`definitions.py`, adhering to the DRY principle.
"""

from __future__ import annotations

__version__ = "0.1.3"

import logging
from collections import defaultdict
from typing import Final, cast

from .const import (  # Import the central definitions list
    DOMAIN,
    POLLING_GROUP_DEFINITIONS,
)
from .definitions import SENSOR_DEFINITIONS
from .models import NodeGroupPayload, SensorDefinition

_LOGGER = logging.getLogger(DOMAIN)

# Dynamically generated structures for polling groups.
# These will be populated by build_polling_groups_from_definitions().
HDG_NODE_PAYLOADS: Final[dict[str, NodeGroupPayload]] = {}
POLLING_GROUP_ORDER: Final[list[str]] = []


def _extract_node_base_for_payload(node_id: str) -> str:
    """
    Remove a single trailing 'T' if present, otherwise leave unchanged.

    Used for payload string generation.
    """
    return node_id.removesuffix("T")


def build_polling_groups_from_definitions() -> None:
    """
    Build the HDG_NODE_PAYLOADS and POLLING_GROUP_ORDER structures dynamically.

    This function reads SENSOR_DEFINITIONS, groups nodes by their 'polling_group',
    and constructs the necessary dictionaries and lists for the coordinator.
    It handles potential duplicate node IDs within a group by using sets.
    """
    _LOGGER.debug("Building polling group structures from SENSOR_DEFINITIONS...")

    nodes_by_polling_group: dict[str, set[str]] = defaultdict(set)

    # First pass: Collect all node IDs from SENSOR_DEFINITIONS, grouped by their polling_group key.
    # This uses the 'polling_group' key defined in SENSOR_DEFINITIONS, which should match
    # one of the 'key' values in the POLLING_GROUP_DEFINITIONS list from const.py.
    valid_polling_group_keys = {pg_def["key"] for pg_def in POLLING_GROUP_DEFINITIONS}

    for _translation_key, definition_dict in SENSOR_DEFINITIONS.items():
        definition = cast(SensorDefinition, definition_dict)
        # Explicitly cast the results of .get() to str or handle potential None if necessary,
        # though the `if` condition below should guard against None for these specific keys.
        polling_group_key = cast(str | None, definition.get("polling_group"))
        hdg_node_id = cast(str | None, definition.get("hdg_node_id"))

        if (
            polling_group_key
            and hdg_node_id
            and polling_group_key in valid_polling_group_keys
        ):
            nodes_by_polling_group[polling_group_key].add(hdg_node_id)
        elif polling_group_key and polling_group_key not in valid_polling_group_keys:
            _LOGGER.warning(
                f"Definition for '{_translation_key}' has unknown polling_group '{polling_group_key}'. Skipping."
            )

    HDG_NODE_PAYLOADS.clear()
    POLLING_GROUP_ORDER.clear()

    # Use a predefined order for groups
    # Iterate through the central POLLING_GROUP_DEFINITIONS list to build the structures.
    # The order in this list determines the POLLING_GROUP_ORDER.

    for group_definition in POLLING_GROUP_DEFINITIONS:
        group_key = group_definition[
            "key"
        ]  # 'key' is a mandatory field in PollingGroupStaticDefinition
        if (
            group_key in nodes_by_polling_group
        ):  # Only build for groups that actually have nodes assigned
            POLLING_GROUP_ORDER.append(group_key)
            sorted_node_ids = sorted(nodes_by_polling_group[group_key])
            payload_base_ids = [
                _extract_node_base_for_payload(nid) for nid in sorted_node_ids
            ]
            payload_str = f"nodes={'T-'.join(payload_base_ids)}T"
            HDG_NODE_PAYLOADS[group_key] = {
                "key": group_key,
                "name": group_definition["name"],
                "nodes": sorted_node_ids,
                "payload_str": payload_str,
                "config_key_scan_interval": group_definition["config_key"],
                "default_scan_interval": group_definition["default_interval"],
            }
    _LOGGER.info(
        f"Finished building polling group structures. {len(HDG_NODE_PAYLOADS)} groups defined."
    )


# Build the structures immediately when the module is imported.
build_polling_groups_from_definitions()
