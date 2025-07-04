"""Central registry for HDG boiler entity and polling group definitions.

This module defines the `HdgEntityRegistry` class, which is responsible for
processing and providing structured access to all entity and polling group
definitions used by the HDG Bavaria Boiler integration. It centralizes the
logic for dynamic group creation and ensures type-safe access to entity metadata.
"""

from __future__ import annotations
import logging
from typing import cast, Final
from itertools import groupby

from .models import NodeGroupPayload, PollingGroupStaticDefinition, SensorDefinition
from .const import DOMAIN, LIFECYCLE_LOGGER_NAME

_LOGGER = logging.getLogger(DOMAIN)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)


class HdgEntityRegistry:
    """Central registry for HDG boiler entity and polling group definitions."""

    def __init__(
        self,
        sensor_definitions: dict[str, SensorDefinition],
        polling_group_definitions: list[PollingGroupStaticDefinition],
    ) -> None:
        """Initialize the HdgEntityRegistry.

        Args:
            sensor_definitions: A dictionary of sensor definitions.
            polling_group_definitions: A list of static polling group definitions.

        """
        self._sensor_definitions: Final[dict[str, SensorDefinition]] = (
            sensor_definitions
        )
        self._polling_group_definitions: Final[list[PollingGroupStaticDefinition]] = (
            polling_group_definitions
        )
        self._polling_group_order: list[str] = []
        self._hdg_node_payloads: dict[str, NodeGroupPayload] = {}
        self._entities_by_node_id: dict[str, SensorDefinition] = {}
        self._writable_entities: list[SensorDefinition] = []

        self._build_registry()

    def _build_registry(self) -> None:
        _LIFECYCLE_LOGGER.debug("Building HDG entity registry...")
        self._build_polling_groups()
        self._index_entities()
        _LIFECYCLE_LOGGER.info(
            f"HDG entity registry built with {len(self._polling_group_order)} polling groups and "
            f"{len(self._sensor_definitions)} entity definitions."
        )

    def _build_polling_groups(self) -> None:
        valid_polling_group_keys = {
            pg_def["key"] for pg_def in self._polling_group_definitions
        }

        sorted_defs = sorted(
            [
                d
                for d in self._sensor_definitions.values()
                if d.get("polling_group") in valid_polling_group_keys
                and d.get("hdg_node_id")
            ],
            key=lambda x: x.get("polling_group", ""),
        )

        self._polling_group_order.clear()
        self._hdg_node_payloads.clear()

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

    def _index_entities(self) -> None:
        self._entities_by_node_id.clear()
        self._writable_entities.clear()
        for _, definition in self._sensor_definitions.items():
            if hdg_node_id := definition.get("hdg_node_id"):
                self._entities_by_node_id[hdg_node_id] = definition
            if definition.get("writable"):
                self._writable_entities.append(definition)

    @staticmethod
    def _extract_node_base_for_payload(node_id: str) -> str:
        """Remove a single trailing 'T' if present, otherwise leave unchanged."""
        return node_id[:-1] if node_id.endswith("T") else node_id

    def get_polling_group_order(self) -> list[str]:
        """Return the ordered list of polling group keys."""
        return self._polling_group_order

    def get_polling_group_payloads(self) -> dict[str, NodeGroupPayload]:
        """Return the dynamically generated HDG node payloads."""
        return self._hdg_node_payloads

    def get_entity_definition_by_node_id(self, node_id: str) -> SensorDefinition | None:
        """Return an entity definition by its HDG node ID."""
        return self._entities_by_node_id.get(node_id)

    def get_writable_entity_definitions(self) -> list[SensorDefinition]:
        """Return a list of all writable entity definitions."""
        return self._writable_entities
