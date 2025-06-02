"""
Data models and type definitions for the HDG Bavaria Boiler integration.

This module centralizes `TypedDict` definitions used across the HDG Bavaria Boiler
integration. These models provide type hinting and structure for entity definitions,
API polling group configurations, and enumeration options.
"""

from __future__ import annotations

__version__ = "0.1.2"

from typing import TypedDict

from homeassistant.helpers.entity import EntityCategory


class SensorDefinition(TypedDict, total=False):
    """
    Defines the properties and Home Assistant platform configuration for an entity
    derived from an HDG boiler data node. This dictionary structure is used within
    `SENSOR_DEFINITIONS` (in `definitions.py`) to specify how raw data from a specific HDG node ID
    should be represented and handled as a Home Assistant entity.

    Attributes:
        hdg_node_id: The raw HDG API node ID (e.g., "22003T").
        translation_key: Key used for localization of entity name and other UI elements.
        polling_group: The key of the polling group this sensor belongs to (e.g., "group_1").
        hdg_data_type: The data type code from the HDG API (e.g., "2" for numeric, "10" for enum).
        hdg_formatter: Specific formatter string from HDG API (e.g., "iTEMP", "iPERC").
        hdg_enum_type: Key for `HDG_ENUM_MAPPINGS` if the node represents an enumeration.
        ha_platform: The Home Assistant platform (e.g., "sensor", "number").
        ha_device_class: The Home Assistant device class (e.g., `SensorDeviceClass.TEMPERATURE`).
        ha_native_unit_of_measurement: The native unit of measurement for the HA entity.
        ha_state_class: The Home Assistant state class (e.g., `SensorStateClass.MEASUREMENT`).
        icon: Optional icon override for the HA entity.
        entity_category: The Home Assistant entity category (e.g., `EntityCategory.DIAGNOSTIC`).
        writable: Boolean indicating if the node value can be set via the API.
        parse_as_type: Internal type hint for parsing the raw string value (e.g., "float", "int", "enum_text").
        setter_type: For writable entities, the type expected by the API setter (e.g., "int", "float1").
        setter_min_val: Minimum allowed value for writable entities.
        setter_max_val: Maximum allowed value for writable entities.
        setter_step: Step value for writable entities.
        normalize_internal_whitespace: If True, internal whitespace in the raw string value
                                       will be normalized (multiple spaces to one) before parsing.
                                       Defaults to False if not specified.
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
    normalize_internal_whitespace: bool | None


class NodeGroupPayload(TypedDict):
    """
    Structure for defining an HDG API node polling group and its configuration.
    Used in `polling_groups.py` to define `HDG_NODE_PAYLOADS`.

    Attributes:
        key: The unique key of the polling group (e.g., "group_1").
        name: A human-readable name for the polling group (e.g., "Realtime Core").
        nodes: A list of HDG node IDs (typically with 'T' suffix) belonging to this group.
        payload_str: The formatted string to be sent as the 'nodes' parameter in the API request
                     for this group.
    """

    # This TypedDict is now built dynamically by polling_manager.py and includes
    # 'config_key_scan_interval' and 'default_scan_interval' from PollingGroupStaticDefinition.
    # For static type checking where this structure is created, ensure all expected keys are present.
    # However, the actual structure used by the coordinator will have more fields.
    # Keeping it minimal here as its primary definition source is dynamic.
    key: str
    name: str
    nodes: list[str]
    payload_str: str
    config_key_scan_interval: str  # Added from PollingGroupStaticDefinition.config_key
    default_scan_interval: (
        int  # Added from PollingGroupStaticDefinition.default_interval
    )


class PollingGroupStaticDefinition(TypedDict):
    """
    Structure for defining the static configuration of a polling group.
    Used in `const.py` for the main list of polling group definitions.
    """

    key: str  # Unique key for the polling group (e.g., "group_1", "group_realtime")
    name: str  # Human-readable name (e.g., "Realtime Core")
    config_key: str  # The key used in Home Assistant configuration (options flow) for scan interval
    default_interval: int  # The default scan interval in seconds


class EnumOption(TypedDict):
    """
    Represents a single option within an enumeration, providing translations.
    Used in `enums.py` for `HDG_ENUM_MAPPINGS`.
    """

    de: str
    en: str
