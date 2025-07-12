"""Central registry for HDG boiler entity and polling group definitions."""

from __future__ import annotations

__version__ = "0.1.4"
import logging
from typing import cast, Final
from itertools import groupby

from .models import NodeGroupPayload, PollingGroupStaticDefinition, SensorDefinition
from .const import DOMAIN, LIFECYCLE_LOGGER_NAME
from .helpers.string_utils import strip_hdg_node_suffix

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
        self._added_entity_counts: dict[str, int] = {
            "sensor": 0,
            "number": 0,
            "select": 0,
        }

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

    def get_entities_for_platform(self, platform: str) -> dict[str, SensorDefinition]:
        """Return a dictionary of entity definitions for a given platform."""
        return {
            key: definition
            for key, definition in self._sensor_definitions.items()
            if definition.get("ha_platform") == platform
        }

    def get_settable_number_definition_by_base_node_id(
        self, base_node_id: str
    ) -> SensorDefinition | None:
        """Find and return the SensorDefinition for a settable 'number' node by its base node ID.

        This method is intended for use by services that need to find a specific
        settable entity definition based on its base node ID.
        """
        settable_definitions = []
        for definition_dict in self._sensor_definitions.values():
            definition = cast(SensorDefinition, definition_dict)
            hdg_node_id_val = definition.get("hdg_node_id")
            if (
                isinstance(hdg_node_id_val, str)
                and strip_hdg_node_suffix(hdg_node_id_val) == base_node_id
                and definition.get("ha_platform") == "number"
                and definition.get("setter_type")
            ):
                settable_definitions.append(definition)

        if not settable_definitions:
            return None
        if len(settable_definitions) > 1:
            _LOGGER.error(
                "Multiple settable 'number' SensorDefinitions found for base node_id '%s': %s. "
                "Please ensure only one settable definition exists per node to avoid ambiguity.",
                base_node_id,
                [repr(d) for d in settable_definitions],
            )
            raise ValueError(f"Ambiguous settable definition for {base_node_id}")

        return settable_definitions[0]

    def increment_added_entity_count(self, platform: str, count: int) -> None:
        """Increment the count of successfully added entities for a given platform."""
        if platform in self._added_entity_counts:
            self._added_entity_counts[platform] += count
        else:
            _LOGGER.warning(
                "Attempted to increment count for unknown platform: %s", platform
            )

    def get_total_added_entities(self) -> int:
        """Return the total count of all successfully added entities across all platforms."""
        return sum(self._added_entity_counts.values())
