"""Provides base entity classes for the HDG Bavaria Boiler integration.

This module defines `HdgBaseEntity`, which offers common properties like
`device_info` and standardized unique ID generation. It also defines
`HdgNodeEntity`, which extends `HdgBaseEntity` for entities that directly
correspond to specific data nodes on the HDG boiler, handling node-specific
availability and attributes.
"""

from __future__ import annotations

__version__ = "0.2.6"
__all__ = ["HdgBaseEntity", "HdgNodeEntity"]

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_ALIAS,
    CONF_HOST_IP,
    DEFAULT_NAME,
    DOMAIN,
    ENTITY_DETAIL_LOGGER_NAME,
    HDG_DATETIME_SPECIAL_TEXT,
    HDG_UNAVAILABLE_STRINGS,
    LIFECYCLE_LOGGER_NAME,
)
from .coordinator import HdgDataUpdateCoordinator
from .helpers.logging_utils import format_for_log
from .helpers.string_utils import normalize_unique_id_component, strip_hdg_node_suffix
from .models import SensorDefinition

_LOGGER = logging.getLogger(DOMAIN)
_ENTITY_DETAIL_LOGGER = logging.getLogger(ENTITY_DETAIL_LOGGER_NAME)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)


class HdgBaseEntity(CoordinatorEntity[HdgDataUpdateCoordinator]):
    """Base class for all HDG Bavaria Boiler integration entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        unique_id_suffix: str,
    ) -> None:
        """Initialize the HDG base entity."""
        _ENTITY_DETAIL_LOGGER.debug(
            "HdgBaseEntity.__init__ for unique_id_suffix: '%s'", unique_id_suffix
        )
        super().__init__(coordinator)

        device_identifier, device_name = self._determine_device_info_components()
        norm_device_identifier = normalize_unique_id_component(device_identifier)
        norm_unique_id_suffix = normalize_unique_id_component(unique_id_suffix)

        self._attr_unique_id = (
            f"{DOMAIN}::{norm_device_identifier}::{norm_unique_id_suffix}"
        )
        self._attr_device_info = self._get_device_info(device_identifier, device_name)

        self._log_entity_details(
            "HdgBaseEntity",
            {
                "unique_id_suffix": unique_id_suffix,
                "final_unique_id": self._attr_unique_id,
                "device_name": device_name,
            },
        )

    def _determine_device_info_components(self) -> tuple[str, str]:
        """Determine the device identifier and name from the config entry."""
        entry = self.coordinator.entry
        device_alias = entry.data.get(CONF_DEVICE_ALIAS)
        device_identifier = device_alias or entry.unique_id or entry.entry_id

        host_ip = entry.data.get(CONF_HOST_IP)
        if name_suffix := device_alias or host_ip:
            device_name = f"{DEFAULT_NAME} ({name_suffix})"
        else:
            device_name = f"{DEFAULT_NAME} (Unknown - {entry.entry_id})"
            _ENTITY_DETAIL_LOGGER.warning(
                "Device alias and host IP missing for entry '%s'. Using fallback name: '%s'",
                entry.entry_id,
                device_name,
            )
        return device_identifier, device_name

    def _get_device_info(self, device_identifier: str, device_name: str) -> DeviceInfo:
        """Generate DeviceInfo for the entity."""
        config_url = getattr(self.coordinator.api_client, "base_url", None)
        _ENTITY_DETAIL_LOGGER.debug(
            "Determined configuration_url '%s' for DeviceInfo.", config_url
        )

        return DeviceInfo(
            identifiers={(DOMAIN, device_identifier)},
            name=device_name,
            manufacturer="HDG Bavaria GmbH",
            model="Boiler Control",
            configuration_url=config_url,
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity being added to Home Assistant."""
        await super().async_added_to_hass()
        _LIFECYCLE_LOGGER.debug(
            "HdgBaseEntity added to HASS: %s (Name: %s, TranslationKey: %s)",
            self.unique_id,
            self.name,
            getattr(self.entity_description, "translation_key", "N/A"),
        )

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        if not self.coordinator or not self.coordinator.last_update_success:
            return False
        if self.coordinator.data is None:
            _ENTITY_DETAIL_LOGGER.debug(
                "Entity %s unavailable: coordinator data is None.", self.unique_id
            )
            return False
        return True


class HdgNodeEntity(HdgBaseEntity):
    """Base class for HDG entities directly corresponding to a specific data node."""

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        description: EntityDescription,
        entity_definition: SensorDefinition,
    ) -> None:
        """Initialize the node-specific HDG entity."""
        _ENTITY_DETAIL_LOGGER.debug("HdgNodeEntity.__init__: %s", description.key)
        self.entity_description = description
        self._entity_definition = entity_definition
        self._node_id = strip_hdg_node_suffix(self._entity_definition["hdg_node_id"])

        base_id = description.translation_key or description.key
        platform = getattr(description, "ha_platform", "sensor")
        unique_id_suffix = f"{base_id}_{platform}"

        super().__init__(coordinator=coordinator, unique_id_suffix=unique_id_suffix)

        # Set attributes only if they exist in the description
        if hasattr(description, "state_class"):
            self._attr_state_class = description.state_class
        if hasattr(description, "device_class"):
            self._attr_device_class = description.device_class
        if hasattr(description, "native_unit_of_measurement"):
            self._attr_native_unit_of_measurement = (
                description.native_unit_of_measurement
            )
        if hasattr(description, "icon"):
            self._attr_icon = description.icon

        # Propagate registry enabled default if present in the definition
        enabled_default = self._entity_definition.get("entity_registry_enabled_default")
        if enabled_default is not None:
            self._attr_entity_registry_enabled_default = enabled_default

    async def async_added_to_hass(self) -> None:
        """Handle entity being added to Home Assistant."""
        await super().async_added_to_hass()

        if self.enabled:
            self.coordinator.register_node(self._node_id)

        _LIFECYCLE_LOGGER.debug(
            "HdgNodeEntity added to HASS: %s (Node ID: %s, Enabled: %s)",
            self.unique_id,
            self._node_id,
            self.enabled,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity being removed from Home Assistant."""
        await super().async_will_remove_from_hass()
        if self.enabled:
            self.coordinator.unregister_node(self._node_id)
        _LIFECYCLE_LOGGER.debug(
            "HdgNodeEntity removed from HASS and unregistered: %s (Node ID: %s)",
            self.unique_id,
            self._node_id,
        )

    @callback
    def async_registry_entry_updated(self) -> None:
        """Handle entity registry update (e.g. enabled/disabled)."""
        if self.enabled:
            self.coordinator.register_node(self._node_id)
        else:
            self.coordinator.unregister_node(self._node_id)

        _LIFECYCLE_LOGGER.debug(
            "HdgNodeEntity registry updated: %s (Node ID: %s, Enabled: %s)",
            self.unique_id,
            self._node_id,
            self.enabled,
        )

    def _is_value_unavailable(self, raw_value: Any) -> bool:
        """Check if the raw value indicates unavailability."""
        if not isinstance(raw_value, str):
            return False

        text_lower = raw_value.lower().strip()
        if text_lower in HDG_UNAVAILABLE_STRINGS:
            return True
        return (
            self.device_class == SensorDeviceClass.TIMESTAMP
            and HDG_DATETIME_SPECIAL_TEXT in text_lower
        )

    @property
    def available(self) -> bool:
        """Determine if the entity is available."""
        entity_id_for_log = self.entity_id if self.hass else self.unique_id

        if not super().available:
            _ENTITY_DETAIL_LOGGER.debug(
                "%s (Node %s): unavailable via HdgBaseEntity",
                entity_id_for_log,
                self._node_id,
            )
            return False

        raw_value = self.coordinator.data.get(self._node_id)
        if raw_value is None:
            _ENTITY_DETAIL_LOGGER.debug(
                "%s (Node %s): unavailable, raw_value is None",
                entity_id_for_log,
                self._node_id,
            )
            return False

        if self._is_value_unavailable(raw_value):
            _ENTITY_DETAIL_LOGGER.debug(
                "%s (Node %s): unavailable, value '%s' is a known unavailable string.",
                entity_id_for_log,
                self._node_id,
                raw_value,
            )
            return False

        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity-specific state attributes for diagnostics."""
        attributes = {
            "hdg_node_id": self._node_id,
            "hdg_data_type": self._entity_definition.get("hdg_data_type"),
            "hdg_formatter": self._entity_definition.get("hdg_formatter"),
            "hdg_enum_type": self._entity_definition.get("hdg_enum_type"),
        }
        if self.coordinator.data:
            raw_value = self.coordinator.data.get(self._node_id)
            if raw_value is not None:
                attributes["hdg_raw_value"] = str(raw_value)[:100]

        return {k: v for k, v in attributes.items() if v is not None}

    def _log_entity_details(self, prefix: str, details: dict[str, Any]) -> None:
        """Log detailed entity information using _ENTITY_DETAIL_LOGGER."""
        _ENTITY_DETAIL_LOGGER.debug(
            "%s: Entity Details: %s", prefix, format_for_log(details)
        )

    def _get_enum_key_from_value(self, raw_value: Any) -> str | None:
        """Get the enum key for a given raw value."""
        options = self._entity_definition.get("options")
        if isinstance(options, dict):
            for key, value in options.items():
                if value == raw_value:
                    return key
        return None
