"""Central registry for HDG boiler entity and polling group definitions."""

from __future__ import annotations

__version__ = "0.3.2"
__all__ = ["HdgEntityRegistry"]

import logging
from collections.abc import Iterable
from itertools import groupby
from typing import cast, Final, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, LIFECYCLE_LOGGER_NAME
from .helpers.string_utils import strip_hdg_node_suffix
from .models import NodeGroupPayload, PollingGroupStaticDefinition, SensorDefinition

_LOGGER = logging.getLogger(DOMAIN)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)


class HdgEntityRegistry:
    """Central registry for HDG boiler entity and polling group definitions."""

    def __init__(
        self,
        sensor_definitions: dict[str, SensorDefinition],
        polling_group_definitions: list[PollingGroupStaticDefinition],
    ) -> None:
        """Initialize the HdgEntityRegistry."""
        self._sensor_definitions: Final = sensor_definitions
        self._polling_group_definitions: Final = polling_group_definitions
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
        """Construct the internal registry, polling groups, and indexes."""
        _LIFECYCLE_LOGGER.debug("Building HDG entity registry...")
        self._build_polling_groups()
        self._index_entities()
        _LIFECYCLE_LOGGER.info(
            "HDG entity registry built with %d polling groups and %d entity definitions.",
            len(self._polling_group_order),
            len(self._sensor_definitions),
        )

    def _get_valid_sorted_sensor_defs(self) -> list[SensorDefinition]:
        """Filter and sort sensor definitions that belong to a valid polling group."""
        valid_pg_keys = {pg_def["key"] for pg_def in self._polling_group_definitions}
        return sorted(
            (
                d
                for d in self._sensor_definitions.values()
                if d.get("polling_group") in valid_pg_keys and d.get("hdg_node_id")
            ),
            key=lambda x: x.get("polling_group", ""),
        )

    def generate_payload_str(self, nodes: list[str]) -> str:
        """Generate a payload string for a given list of node IDs."""
        payload_base_ids = [self._strip_trailing_t(nid) for nid in nodes]
        return f"nodes={'T-'.join(payload_base_ids)}T"

    def _create_node_group_payload(
        self, group_key: str, nodes_in_group: list[str]
    ) -> NodeGroupPayload | None:
        """Create a payload object for a polling group."""
        if group_def := next(
            (gd for gd in self._polling_group_definitions if gd["key"] == group_key),
            None,
        ):
            return {
                "key": group_key,
                "name": group_key.replace("_", " ").title(),
                "nodes": nodes_in_group,
                "payload_str": self.generate_payload_str(nodes_in_group),
                "default_scan_interval": group_def["default_interval"],
            }
        else:
            return None

    def _process_polling_group(
        self, group_key: str, group_iter: Iterable[SensorDefinition]
    ) -> None:
        """Process a single polling group and add it to the registry."""
        if not group_key:
            return

        nodes_in_group = sorted(
            {cast(str, d["hdg_node_id"]) for d in group_iter if d.get("hdg_node_id")}
        )
        if not nodes_in_group:
            return

        if payload := self._create_node_group_payload(group_key, nodes_in_group):
            self._polling_group_order.append(group_key)
            self._hdg_node_payloads[group_key] = payload

    def _build_polling_groups(self) -> None:
        """Filter and group sensor definitions into polling groups."""
        sorted_defs = self._get_valid_sorted_sensor_defs()
        self._polling_group_order.clear()
        self._hdg_node_payloads.clear()

        for group_key, group_iter in groupby(
            sorted_defs, lambda x: x.get("polling_group", "")
        ):
            self._process_polling_group(group_key, group_iter)

    def _index_entities(self) -> None:
        """Create indexes for efficient entity lookup."""
        self._entities_by_node_id.clear()
        self._writable_entities.clear()
        for definition in self._sensor_definitions.values():
            if hdg_node_id := definition.get("hdg_node_id"):
                self._entities_by_node_id[hdg_node_id] = definition
            if definition.get("writable"):
                self._writable_entities.append(definition)

    @staticmethod
    def _strip_trailing_t(node_id: str) -> str:
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
        """Find a settable 'number' definition by its base node ID."""
        for definition in self._sensor_definitions.values():
            hdg_node_id = definition.get("hdg_node_id")
            if (
                isinstance(hdg_node_id, str)
                and strip_hdg_node_suffix(hdg_node_id) == base_node_id
                and definition.get("ha_platform") == "number"
                and definition.get("setter_type")
            ):
                return definition
        return None

    def get_node_id_by_key(self, key: str) -> str | None:
        """Return the HDG node ID for a given entity key."""
        return self._sensor_definitions.get(key, {}).get("hdg_node_id")

    def increment_added_entity_count(self, platform: str, count: int) -> None:
        """Increment the count of successfully added entities for a given platform."""
        if platform in self._added_entity_counts:
            self._added_entity_counts[platform] += count
        else:
            _LOGGER.warning(
                "Attempted to increment count for unknown platform: %s", platform
            )

    def get_total_added_entities(self) -> int:
        """Return the total count of all successfully added entities."""
        return sum(self._added_entity_counts.values())

    def resolve_node_id_from_entity_entry(self, entry: er.RegistryEntry) -> str | None:
        """Return canonical node_id for a registry entry, or None."""
        # unique_id: "hdg_boiler::{device}::{key}_{platform}"
        parts = entry.unique_id.split("::")
        if len(parts) != 3:
            return None

        suffix = parts[2]
        for plat in ["_sensor", "_number", "_select"]:
            if suffix.endswith(plat):
                suffix = suffix[: -len(plat)]
                break

        node_id = self.get_node_id_by_key(suffix)
        return strip_hdg_node_suffix(node_id) if node_id else None

    def get_default_active_node_ids(self) -> set[str]:
        """Return canonical node_ids for first-time setup."""
        result: set[str] = set()
        for definition in self._sensor_definitions.values():
            if definition.get("entity_registry_enabled_default", True):
                if node_id := definition.get("hdg_node_id"):
                    result.add(strip_hdg_node_suffix(node_id))
        return result

    def get_optimized_payload_for_group(
        self, group_key: str, active_node_ids: set[str]
    ) -> tuple[str | None, int, int]:
        """Return (payload_str, active_count, total_count) for a group."""
        all_group_nodes = self.get_polling_group_payloads()[group_key]["nodes"]
        active_group_nodes = [
            n for n in all_group_nodes if strip_hdg_node_suffix(n) in active_node_ids
        ]

        if not active_group_nodes:
            return None, 0, len(all_group_nodes)

        payload_str = self.generate_payload_str(active_group_nodes)
        return payload_str, len(active_group_nodes), len(all_group_nodes)
