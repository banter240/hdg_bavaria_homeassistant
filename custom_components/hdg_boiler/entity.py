"""
Provides base entity classes for the HDG Bavaria Boiler integration.

This module defines `HdgBaseEntity`, which offers common properties like
`device_info` and standardized unique ID generation. It also defines
`HdgNodeEntity`, which extends `HdgBaseEntity` for entities that directly
correspond to specific data nodes on the HDG boiler, handling node-specific
availability and attributes.
"""

__version__ = "0.8.5"

import logging
from typing import Any, cast

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_ALIAS,
    CONF_HOST_IP,
    DEFAULT_NAME,
    DOMAIN,
    HDG_DATETIME_SPECIAL_TEXT,
    HDG_UNAVAILABLE_STRINGS,
)
from .coordinator import HdgDataUpdateCoordinator
from .helpers.string_utils import normalize_unique_id_component

_LOGGER = logging.getLogger(DOMAIN)


class HdgBaseEntity(CoordinatorEntity[HdgDataUpdateCoordinator]):
    """
    Base class for all HDG Bavaria Boiler integration entities.

    This class provides common properties such as `device_info` and standardized
    unique ID generation. It ensures that entities are correctly grouped under their
    respective device in Home Assistant.

    Setting `_attr_has_entity_name = True` enables Home Assistant to use
    the `translation_key` from an `EntityDescription` for localized entity naming.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        unique_id_suffix: str,  # Suffix to make the entity's unique_id distinct
    ) -> None:
        """
        Initialize the HDG base entity.

        Args:
            coordinator: The data update coordinator for the integration.
            unique_id_suffix: A string suffix used to create a unique ID for this
                              entity within the integration's domain and device.
                              Typically, this is the `translation_key` or a node ID.
        """
        _LOGGER.debug(
            f"HdgBaseEntity.__init__ for unique_id_suffix: '{unique_id_suffix}'"
        )
        super().__init__(coordinator)

        device_alias = self.coordinator.entry.data.get(CONF_DEVICE_ALIAS)
        # Use alias, HA unique_id (from config entry), or entry_id as device identifier.
        device_identifier = (
            device_alias
            or self.coordinator.entry.unique_id
            or self.coordinator.entry.entry_id
        )

        host_ip = self.coordinator.entry.data.get(CONF_HOST_IP)
        # Determine device_name: Prefer alias, then host_ip, then a fallback.
        if device_alias or host_ip:
            device_name = f"{DEFAULT_NAME} ({device_alias or host_ip})"
        else:
            device_name = (
                f"{DEFAULT_NAME} (Unknown Device - {self.coordinator.entry.entry_id})"
            )
            _LOGGER.warning(
                "Device alias and host IP are both missing for config entry '%s'. Using fallback device name: '%s'",
                self.coordinator.entry.entry_id,
                device_name,
            )

        norm_device_identifier = normalize_unique_id_component(device_identifier)
        norm_unique_id_suffix = normalize_unique_id_component(unique_id_suffix)

        _LOGGER.debug(
            f"HdgBaseEntity: Using device_identifier: '{device_identifier}' for unique_id_suffix: '{unique_id_suffix}' (normalized: '{norm_device_identifier}', '{norm_unique_id_suffix}')"
        )
        self._attr_unique_id = (
            f"{DOMAIN}::{norm_device_identifier}::{norm_unique_id_suffix}"
        )
        _LOGGER.debug(
            f"HdgBaseEntity: Final _attr_unique_id for '{unique_id_suffix}': '{self._attr_unique_id}'"
        )
        _LOGGER.debug(
            f"HdgBaseEntity: Using device_name: '{device_name}' for unique_id_suffix: '{unique_id_suffix}'"
        )

        config_url = getattr(
            getattr(self.coordinator, "api_client", None), "base_url", None
        )
        if config_url:
            _LOGGER.debug(
                f"HdgBaseEntity: Determined configuration_url '{config_url}' for DeviceInfo for '{unique_id_suffix}'"
            )
        else:
            _LOGGER.info(
                f"HdgBaseEntity: config_url could not be determined for unique_id_suffix '{unique_id_suffix}'. "
                "This may indicate a misconfiguration or the API client is not fully initialized."
            )

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_identifier)},
            name=device_name,
            manufacturer="HDG Bavaria GmbH",  # Constant manufacturer name.
            model="Boiler Control",  # Generic model; can be enhanced if API provides specifics.
            configuration_url=config_url,
        )
        _LOGGER.debug(
            f"HdgBaseEntity: Final _attr_device_info for '{unique_id_suffix}': {self._attr_device_info}"
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity being added to Home Assistant."""
        await super().async_added_to_hass()
        _LOGGER.debug(
            f"HdgBaseEntity.async_added_to_hass for {self.unique_id if hasattr(self, 'unique_id') else 'Unknown Unique ID'}. "
            f"Name: {self.name if hasattr(self, 'name') else 'N/A'}, "
            f"HasEntityName: {self.has_entity_name if hasattr(self, 'has_entity_name') else 'N/A'}, "
            f"TranslationKey: {self.entity_description.translation_key if hasattr(self, 'entity_description') and self.entity_description else 'N/A'}"
        )

    @property
    def available(self) -> bool:
        """
        Return True if the entity is available.
        Availability is based on the coordinator's data fetching success and
        whether the coordinator's data store has been initialized.
        A warning is logged if data is None but last_update_success is True,
        as this indicates an inconsistent state.
        """
        if self.coordinator is None or self.coordinator.data is None:
            if self.coordinator is not None and self.coordinator.last_update_success:
                _LOGGER.warning(
                    f"Entity {self.entity_id if self.hass else self.unique_id}: Coordinator data is None, "
                    "but last_update_success is True. Treating as unavailable to prevent errors."
                )
            return False
        return cast(bool, self.coordinator.last_update_success)


class HdgNodeEntity(HdgBaseEntity):
    """
    Base class for HDG entities directly corresponding to a specific data node.

    Extends `HdgBaseEntity` by adding node-specific logic, such as storing the
    HDG node ID and its definition (from `SENSOR_DEFINITIONS`). It also refines
    availability checks based on the presence and content of the specific node's data.
    """

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        node_id: str,  # The base HDG node ID (without TUVWXY suffix)
        entity_definition: dict[str, Any],  # Full definition from SENSOR_DEFINITIONS
    ) -> None:
        """
        Initialize the node-specific HDG entity.

        Args:
            coordinator: The data update coordinator.
            node_id: The base HDG node ID (e.g., "22003") for data retrieval.
                     Suffixes like 'T' are typically stripped before being passed here.
            entity_definition: The full `SensorDefinition` dictionary for this entity.
        """
        _LOGGER.debug(
            f"HdgNodeEntity.__init__ called. Node ID: '{node_id}', Entity Definition: {entity_definition}"
        )
        self._node_id = node_id  # Base HDG node ID for data retrieval.
        self._entity_definition = entity_definition  # Full SENSOR_DEFINITIONS entry.

        # Use 'translation_key' for unique_id_suffix if available, else node_id.
        unique_id_suffix = self._entity_definition.get("translation_key", self._node_id)
        _LOGGER.debug(
            f"HdgNodeEntity: Determined unique_id_suffix as '{unique_id_suffix}' for node_id '{node_id}'"
        )
        super().__init__(coordinator=coordinator, unique_id_suffix=unique_id_suffix)
        # Name-related attributes (name, translation_key) are primarily handled by the EntityDescription
        # passed to platform-specific entities (e.g., HdgBoilerSensor, HdgBoilerNumber).
        _LOGGER.debug(
            f"HdgNodeEntity {unique_id_suffix} (Node ID: {self._node_id}): Name setup is delegated to the platform-specific entity "
            "which should use an EntityDescription with a translation_key."
        )

        self._attr_device_class = self._entity_definition.get("ha_device_class")
        _LOGGER.debug(
            f"HdgNodeEntity {unique_id_suffix}: Set _attr_device_class to: {self._attr_device_class}"
        )
        self._attr_native_unit_of_measurement = self._entity_definition.get(
            "ha_native_unit_of_measurement"
        )
        _LOGGER.debug(
            f"HdgNodeEntity {unique_id_suffix}: Set _attr_native_unit_of_measurement to: {self._attr_native_unit_of_measurement}"
        )
        self._attr_state_class = self._entity_definition.get("ha_state_class")
        _LOGGER.debug(
            f"HdgNodeEntity {unique_id_suffix}: Set _attr_state_class to: {self._attr_state_class}"
        )
        self._attr_icon = self._entity_definition.get("icon")
        _LOGGER.debug(
            f"HdgNodeEntity {unique_id_suffix}: Set _attr_icon to: {self._attr_icon}"
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity being added to Home Assistant."""
        _LOGGER.debug(
            f"HdgNodeEntity.async_added_to_hass PRE-SUPER for {self.unique_id}. "
            f"Name: {self.name if hasattr(self, 'name') else 'N/A'}, "
            f"HasEntityName: {self.has_entity_name if hasattr(self, 'has_entity_name') else 'N/A'}, "
            f"TranslationKey: {self.entity_description.translation_key if hasattr(self, 'entity_description') and self.entity_description else 'N/A'}"
        )
        await super().async_added_to_hass()
        _LOGGER.debug(
            f"HdgNodeEntity.async_added_to_hass POST-SUPER for {self.unique_id}. "
            f"Name: {self.name if hasattr(self, 'name') else 'N/A'}, "
            f"HasEntityName: {self.has_entity_name if hasattr(self, 'has_entity_name') else 'N/A'}, "
            f"TranslationKey: {self.entity_description.translation_key if hasattr(self, 'entity_description') and self.entity_description else 'N/A'}"
        )

    @property
    def available(self) -> bool:
        """
        Determine if the entity is available.

        This method first checks the base availability (coordinator status and data store
        initialization) via `super().available`. If the base is available, it then
        verifies the presence of this entity's specific node ID in the coordinator's
        data. It also checks if the raw string value for this node matches any known
        "unavailable" markers from the HDG API (e.g., "---", "unavailable").
        """
        if not super().available:
            # Base availability (coordinator status, data store initialized) failed.
            return False

        raw_value = self.coordinator.data.get(self._node_id)
        if raw_value is None:
            return False

        # Check for known "unavailable" markers from the HDG API if value is a string.
        if isinstance(raw_value, str):
            text_lower = raw_value.lower().strip()
            if text_lower in HDG_UNAVAILABLE_STRINGS:
                return False
            if (
                self._attr_device_class == SensorDeviceClass.TIMESTAMP
                and HDG_DATETIME_SPECIAL_TEXT in text_lower
            ):
                return False
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """
        Return entity-specific state attributes, primarily for diagnostic purposes.

        Includes the HDG node ID, data type, formatter, enum type (if applicable),
        and a sample of the raw value from the coordinator. These attributes can
        be helpful for debugging and understanding the entity's underlying data.
        """
        attributes = {
            "hdg_node_id": self._node_id,  # Base HDG node ID for this entity.
            "hdg_data_type": self._entity_definition.get("hdg_data_type"),
            "hdg_formatter": self._entity_definition.get("hdg_formatter"),
            "hdg_enum_type": self._entity_definition.get("hdg_enum_type"),
        }
        if self.coordinator.data is not None:
            raw_value = self.coordinator.data.get(self._node_id)
            if raw_value is not None:
                # Add raw value for debugging, but keep it concise for diagnostics.
                attributes["hdg_raw_value"] = str(raw_value)[:100]

        return {k: v for k, v in attributes.items() if v is not None}
