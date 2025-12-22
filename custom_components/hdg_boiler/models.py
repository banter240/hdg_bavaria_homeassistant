"""Data models and type definitions for the HDG Bavaria Boiler integration.

This module centralizes `TypedDict` definitions used across the integration.
These models provide type hinting and structure for entity definitions,
API polling group configurations, and enumeration options.
"""

from __future__ import annotations

__version__ = "0.1.7"


from typing import TypedDict

from homeassistant.helpers.entity import EntityCategory

__all__ = [
    "SensorDefinition",
    "NodeGroupPayload",
    "PollingGroupStaticDefinition",
    "EnumOption",
]


class SensorDefinition(TypedDict, total=False):
    """Define the properties and HA platform configuration for an entity.

    This dictionary structure is used within `SENSOR_DEFINITIONS` to specify how
    raw data from a specific HDG node ID should be represented and handled
    as a Home Assistant entity.

    Attributes:
        hdg_node_id: The raw HDG API node ID (e.g., "22003T").
        translation_key: Key for localization of the entity name.
        polling_group: The key of the polling group this sensor belongs to.

        hdg_data_type: The data type code from the HDG API (e.g., "2" for numeric).
        hdg_formatter: Specific formatter string from HDG API (e.g., "iTEMP").
        hdg_enum_type: Key for `HDG_ENUM_MAPPINGS` if the node is an enumeration.

        ha_platform: The Home Assistant platform (e.g., "sensor", "number").
        ha_device_class: The Home Assistant device class (e.g., `SensorDeviceClass.TEMPERATURE`).
        ha_native_unit_of_measurement: The native unit for the HA entity.
        ha_state_class: The Home Assistant state class (e.g., `SensorStateClass.MEASUREMENT`).
        icon: Optional icon override for the HA entity.
        entity_category: The Home Assistant entity category (e.g., `EntityCategory.DIAGNOSTIC`).

        writable: Boolean indicating if the node value can be set via the API.
        parse_as_type: Internal type hint for parsing the raw string value (e.g., "float").
        normalize_internal_whitespace: If True, normalizes internal whitespace in the raw string.

        setter_type: For writable entities, the type expected by the API setter (e.g., "int").
        setter_min_val: Minimum allowed value for writable entities.
        setter_max_val: Maximum allowed value for writable entities.
        setter_step: Step value for writable entities.
        options: A list of valid string options for a `select` entity.

    """

    hdg_node_id: str
    translation_key: str
    polling_group: str
    hdg_data_type: str | None
    hdg_formatter: str | None
    hdg_enum_type: str | None
    ha_platform: str
    ha_device_class: str | None
    ha_native_unit_of_measurement: str | None
    ha_state_class: str | None
    icon: str | None
    entity_category: EntityCategory | None
    writable: bool
    parse_as_type: str | None
    setter_type: str | None
    setter_min_val: float | None
    setter_max_val: float | None
    setter_step: float | None
    options: list[str] | None
    normalize_internal_whitespace: bool | None
    uppercase_value: bool | None
    entity_registry_enabled_default: bool | None


class NodeGroupPayload(TypedDict):
    """Define the structure for an HDG API node polling group.

    Used in `polling_groups.py` to define `HDG_NODE_PAYLOADS`.

    Attributes:
        key: The unique key of the polling group (e.g., "group_1").
        name: A human-readable name for the polling group.
        nodes: A list of HDG node IDs belonging to this group.
        payload_str: The formatted string for the 'nodes' API parameter.
        default_scan_interval: The default scan interval in seconds.

    """

    key: str
    name: str
    nodes: list[str]
    payload_str: str
    default_scan_interval: int


class PollingGroupStaticDefinition(TypedDict):
    """Define the static configuration of a polling group.

    Used in `const.py` for the main list of polling group definitions.

    Attributes:
        key: Unique key for the polling group (e.g., "group_1").
        default_interval: The default scan interval in seconds.

    """

    key: str
    default_interval: int


class EnumOption(TypedDict):
    """Represent a single option within an enumeration, with translations.

    Used in `enums.py` for `HDG_ENUM_MAPPINGS`.
    """

    de: str
    en: str
