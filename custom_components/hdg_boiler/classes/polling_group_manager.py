"""Manages the dynamic creation of polling group structures from entity definitions.

This module contains the logic to read the `SENSOR_DEFINITIONS` from
`definitions.py` and dynamically build the `HDG_NODE_PAYLOADS` and
`POLLING_GROUP_ORDER` structures required by the data update coordinator.
This centralizes the definition of nodes and their polling groups in
`definitions.py`, adhering to the DRY principle.
"""

from __future__ import annotations

__version__ = "0.2.0"

import logging
from itertools import groupby
from typing import cast

from ..const import (
    DOMAIN,
    LIFECYCLE_LOGGER_NAME,
)
from ..models import NodeGroupPayload, PollingGroupStaticDefinition, SensorDefinition

_LOGGER = logging.getLogger(DOMAIN)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)


class PollingGroupManager:
    """Manages the dynamic creation and access of polling group structures."""

    def __init__(
        self,
        sensor_definitions: dict,
        polling_group_definitions: list[PollingGroupStaticDefinition],
    ) -> None:
        """Initialize the PollingGroupManager and build polling groups."""
        self._hdg_node_payloads: dict[str, NodeGroupPayload] = {}
        self._polling_group_order: list[str] = []
        self._sensor_definitions = sensor_definitions
        self._polling_group_definitions = polling_group_definitions
        self._build_polling_groups_from_definitions()

    @property
    def hdg_node_payloads(self) -> dict[str, NodeGroupPayload]:
        """Return the dynamically generated HDG node payloads."""
        return self._hdg_node_payloads

    @property
    def polling_group_order(self) -> list[str]:
        """Return the ordered list of polling group keys."""
        return self._polling_group_order

    @staticmethod
    def _extract_node_base_for_payload(node_id: str) -> str:
        """Remove a single trailing 'T' if present, otherwise leave unchanged."""
        return node_id[:-1] if node_id.endswith("T") else node_id

    def _build_polling_groups_from_definitions(self) -> None:
        _LIFECYCLE_LOGGER.debug(
            "Building polling group structures from SENSOR_DEFINITIONS..."
        )

        valid_polling_group_keys = {
            pg_def["key"] for pg_def in self._polling_group_definitions
        }

        # Filter and sort definitions by polling_group
        sorted_defs = sorted(
            [
                cast(SensorDefinition, d)
                for d in self._sensor_definitions.values()
                if d.get("polling_group") in valid_polling_group_keys
                and d.get("hdg_node_id")
            ],
            key=lambda x: x.get("polling_group", ""),
        )

        self._hdg_node_payloads.clear()
        self._polling_group_order.clear()

        # Group by polling_group_key
        for group_key, group_iter in groupby(
            sorted_defs, key=lambda x: x.get("polling_group", "")
        ):
            if not group_key:
                continue

            group_definitions = list(group_iter)
            nodes_in_group = sorted(
                {
                    cast(str, d.get("hdg_node_id"))
                    for d in group_definitions
                    if d.get("hdg_node_id")
                }
            )

            if not nodes_in_group:
                continue

            group_definition = next(
                (
                    gd
                    for gd in self._polling_group_definitions
                    if gd["key"] == group_key
                ),
                None,
            )
            if not group_definition:
                continue

            self._polling_group_order.append(group_key)
            payload_base_ids = [
                self._extract_node_base_for_payload(nid) for nid in nodes_in_group
            ]
            payload_str = f"nodes={'T-'.join(payload_base_ids)}T"
            self._hdg_node_payloads[group_key] = {
                "key": group_key,
                "name": group_key.replace("_", " ").title(),
                "nodes": nodes_in_group,
                "payload_str": payload_str,
                "default_scan_interval": group_definition["default_interval"],
            }

        _LIFECYCLE_LOGGER.info(
            f"Finished building polling group structures. {len(self._hdg_node_payloads)} groups defined."
        )
