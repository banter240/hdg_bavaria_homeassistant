"""Data models and type definitions for the HDG Bavaria Boiler integration.

This module centralizes `TypedDict` definitions used across the integration.
These models provide type hinting and structure for entity definitions,
API polling group configurations, and enumeration options.
"""

from __future__ import annotations


from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypedDict

from homeassistant.helpers.entity import EntityCategory

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .coordinator import HdgDataUpdateCoordinator

__all__ = [
    "SensorDefinition",
    "NodeGroupPayload",
    "PollingGroupStaticDefinition",
    "EnumOption",
    "CommandType",
    "HdgCommand",
    "PollingState",
]


class CommandType(StrEnum):
    """Types of API commands."""

    GET_NODES = "get_nodes"
    SET_NODE = "set_node"


@dataclass(slots=True)
class HdgCommand:
    """Represents a queued API command."""

    cmd_type: CommandType
    context_key: str | None = None
    node_id: str | None = None
    node_ids: list[str] | None = None
    value: str | None = None


@dataclass(slots=True)
class PollingState:
    """Represents the current state of API polling."""

    consecutive_failures: int = 0
    consecutive_connection_failures: int = 0
    consecutive_preemption_failures: int = 0
    last_update_success_time: datetime | None = None
    last_update_times: dict[str, float] = field(default_factory=dict)
    failed_group_retry_info: dict[str, dict[str, Any]] = field(default_factory=dict)


class _SensorDefinitionRequired(TypedDict):
    """Required fields present on every entity definition."""

    hdg_node_id: str
    translation_key: str
    polling_group: str
    ha_platform: str
    writable: bool
    entity_registry_enabled_default: bool


class SensorDefinition(_SensorDefinitionRequired, total=False):
    """Define the properties and HA platform configuration for an entity.

    Required fields (always present) are inherited from _SensorDefinitionRequired.
    All fields below are optional — present only when explicitly set.
    """

    hdg_data_type: str | None
    hdg_formatter: str | None
    hdg_enum_type: str | None
    ha_device_class: str | None
    ha_native_unit_of_measurement: str | None
    ha_state_class: str | None
    icon: str | None
    entity_category: EntityCategory | None
    parse_as_type: str | None
    setter_type: str | None
    setter_min_val: float | None
    setter_max_val: float | None
    setter_step: float | None
    options: list[str] | None
    normalize_internal_whitespace: bool | None
    uppercase_value: bool | None
    # Optional hardware group this entity belongs to.
    # When set, entity_registry_enabled_default is driven by the corresponding
    # CONF_ENABLE_* option rather than the hardcoded definition value.
    component_group: str | None
    # Definition-based value/set hooks.
    # When set, entity classes delegate all read/write logic to these callables
    # instead of the default parse_sensor_value / async_set_node_value paths.
    value_fn: Callable[[HdgDataUpdateCoordinator], Any] | None
    set_fn: Callable[[HdgDataUpdateCoordinator, str], Awaitable[None]] | None


class NodeGroupPayload(TypedDict):
    """Define the structure for an HDG API node polling group."""

    key: str
    name: str
    nodes: list[str]
    default_scan_interval: int


class PollingGroupStaticDefinition(TypedDict):
    """Define the static configuration of a polling group."""

    key: str
    default_interval: int


class EnumOption(TypedDict):
    """Represent a single option within an enumeration, with translations."""

    de: str
    en: str
