"""Provides base entity classes for the HDG Bavaria Boiler integration.

This module defines `HdgBaseEntity`, which offers common properties like
`device_info` and standardized unique ID generation. It also defines
`HdgNodeEntity`, which extends `HdgBaseEntity` for entities that directly
correspond to specific data nodes on the HDG boiler, handling node-specific
availability and attributes.
"""

from __future__ import annotations

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
    ENTITY_DETAIL_LOGGER_NAME,
    LIFECYCLE_LOGGER_NAME,
)
from .coordinator import HdgDataUpdateCoordinator
from .helpers.string_utils import normalize_unique_id_component
from .helpers.logging_utils import format_for_log

_LOGGER = logging.getLogger(DOMAIN)
_ENTITY_DETAIL_LOGGER = logging.getLogger(ENTITY_DETAIL_LOGGER_NAME)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)


class HdgBaseEntity(CoordinatorEntity[HdgDataUpdateCoordinator]):
    """Base class for all HDG Bavaria Boiler integration entities.

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
        """Initialize the HDG base entity.

        Args:
            coordinator: The data update coordinator for the integration.
            unique_id_suffix: A string suffix used to create a unique ID for this
                              entity within the integration's domain and device.
                              Typically, this is the `translation_key` or a node ID.

        """
        _ENTITY_DETAIL_LOGGER.debug(
            f"HdgBaseEntity.__init__ for unique_id_suffix: '{unique_id_suffix}'"
        )
        super().__init__(coordinator)

        device_alias = self.coordinator.entry.data.get(CONF_DEVICE_ALIAS)
        device_identifier = (
            device_alias
            or self.coordinator.entry.unique_id
            or self.coordinator.entry.entry_id
        )

        host_ip = self.coordinator.entry.data.get(CONF_HOST_IP)
        if device_alias or host_ip:
            device_name = f"{DEFAULT_NAME} ({device_alias or host_ip})"
        else:
            device_name = (
                f"{DEFAULT_NAME} (Unknown Device - {self.coordinator.entry.entry_id})"
            )
            _ENTITY_DETAIL_LOGGER.warning(
                "Device alias and host IP are both missing for config entry '%s'. Using fallback device name: '%s'",
                self.coordinator.entry.entry_id,
                device_name,
            )

        norm_device_identifier = normalize_unique_id_component(device_identifier)
        norm_unique_id_suffix = normalize_unique_id_component(unique_id_suffix)

        self._attr_unique_id = (
            f"{DOMAIN}::{norm_device_identifier}::{norm_unique_id_suffix}"
        )

        self._attr_device_info = self._get_device_info(
            device_alias, device_identifier, device_name, unique_id_suffix
        )

        self._log_entity_details(
            "HdgBaseEntity",
            {
                "device_identifier": format_for_log(device_identifier),
                "unique_id_suffix": format_for_log(unique_id_suffix),
                "normalized_device_identifier": format_for_log(norm_device_identifier),
                "normalized_unique_id_suffix": format_for_log(norm_unique_id_suffix),
                "final_unique_id": format_for_log(self._attr_unique_id),
                "device_name": format_for_log(device_name),
                "final_device_info": format_for_log(self._attr_device_info),
            },
        )

    def _get_device_info(
        self,
        device_alias: str | None,
        device_identifier: str,
        device_name: str,
        unique_id_suffix: str,
    ) -> DeviceInfo:
        """Generate DeviceInfo for the entity."""
        config_url = None
        if api_access_manager_obj := getattr(
            self.coordinator, "api_access_manager", None
        ):
            if api_client_obj := getattr(api_access_manager_obj, "_api_client", None):
                config_url = getattr(api_client_obj, "base_url", None)

        if config_url:
            _ENTITY_DETAIL_LOGGER.debug(
                f"HdgBaseEntity: Determined configuration_url '{config_url}' for DeviceInfo for '{unique_id_suffix}'"
            )
        else:
            _ENTITY_DETAIL_LOGGER.info(
                f"HdgBaseEntity: config_url could not be determined for unique_id_suffix '{unique_id_suffix}'. "
                "This may indicate the API client is not fully initialized."
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
            "HdgBaseEntity.async_added_to_hass for %s. Name: %s, HasEntityName: %s, TranslationKey: %s",
            self.unique_id,
            self.name,
            self.has_entity_name,
            self.entity_description.translation_key
            if self.entity_description
            else "N/A",
        )

    @property
    def available(self) -> bool:
        """Return True if the entity is available.

        Availability is based on the coordinator's data fetching success and
        whether the coordinator's data store has been initialized.
        A warning is logged if data is None but last_update_success is True,
        as this indicates an inconsistent state.
        """
        if self.coordinator is None or self.coordinator.data is None:
            if self.coordinator and self.coordinator.last_update_success:
                _ENTITY_DETAIL_LOGGER.debug(
                    "Entity %s: Coordinator data is None, "
                    "but last_update_success is True. Treating as unavailable to prevent errors.",
                    self.entity_id if self.hass else self.unique_id,
                )
            return False
        return cast(bool, self.coordinator.last_update_success)


class HdgNodeEntity(HdgBaseEntity):
    """Base class for HDG entities directly corresponding to a specific data node.

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
        """Initialize the node-specific HDG entity.

        Args:
            coordinator: The data update coordinator.
            node_id: The base HDG node ID (e.g., "22003") for data retrieval.
                     Suffixes like 'T' are typically stripped before being passed here.
            entity_definition: The full `SensorDefinition` dictionary for this entity.

        """
        _ENTITY_DETAIL_LOGGER.debug(
            f"HdgNodeEntity.__init__ called. Node ID: '{node_id}', Entity Definition: {entity_definition}"
        )
        self._node_id = node_id  # Base HDG node ID for data retrieval.
        self._entity_definition = entity_definition  # Full SENSOR_DEFINITIONS entry.

        # Use 'translation_key' for unique_id_suffix if available, else node_id.
        unique_id_suffix = self._entity_definition.get("translation_key", self._node_id)
        super().__init__(coordinator=coordinator, unique_id_suffix=unique_id_suffix)

        self._attr_device_class = self._entity_definition.get("ha_device_class")
        self._attr_native_unit_of_measurement = self._entity_definition.get(
            "ha_native_unit_of_measurement"
        )
        self._attr_state_class = self._entity_definition.get("ha_state_class")
        self._attr_icon = self._entity_definition.get("icon")

        self._log_entity_details(
            f"HdgNodeEntity {unique_id_suffix} (Node ID: {self._node_id})",
            {
                "determined_unique_id_suffix": unique_id_suffix,
                "name_setup_delegated": "True",
                "device_class": self._attr_device_class,
                "native_unit_of_measurement": self._attr_native_unit_of_measurement,
                "state_class": self._attr_state_class,
                "icon": self._attr_icon,
            },
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity being added to Home Assistant."""
        _LIFECYCLE_LOGGER.debug(
            f"HdgNodeEntity.async_added_to_hass PRE-SUPER for {self.unique_id}. "
            f"Name: {self.name}, "
            f"HasEntityName: {self.has_entity_name}, "
            f"TranslationKey: {
                self.entity_description.translation_key
                if self.entity_description
                else 'N/A'
            }"
        )
        await super().async_added_to_hass()
        _LIFECYCLE_LOGGER.debug(
            f"HdgNodeEntity.async_added_to_hass POST-SUPER for {self.unique_id}. "
            f"Name: {self.name}, "
            f"HasEntityName: {self.has_entity_name}, "
            f"TranslationKey: {
                self.entity_description.translation_key
                if self.entity_description
                else 'N/A'
            }"
        )

    @property
    def available(self) -> bool:
        """Determine if the entity is available.

        This method first checks the base availability (coordinator status and data store
        initialization) via `super().available`. If the base is available, it then
        verifies the presence of this entity's specific node ID in the coordinator's
        data. It also checks if the raw string value for this node matches any known
        "unavailable" markers from the HDG API (e.g., "---", "unavailable").
        """
        entity_id_for_log = self.entity_id if self.hass else self.unique_id

        if not super().available:
            _ENTITY_DETAIL_LOGGER.debug(
                "Entity %s (Node ID: %s): Not available because super().available is False.",
                entity_id_for_log,
                self._node_id,
            )
            return False

        raw_value = self.coordinator.data.get(self._node_id)
        if raw_value is None:
            _ENTITY_DETAIL_LOGGER.debug(
                "Entity %s (Node ID: %s): Not available because raw_value is None in coordinator data.",
                entity_id_for_log,
                self._node_id,
            )
            return False

        # Check for known "unavailable" markers from the HDG API if value is a string.
        if isinstance(raw_value, str):
            text_lower = raw_value.lower().strip()
            if text_lower in HDG_UNAVAILABLE_STRINGS:
                _ENTITY_DETAIL_LOGGER.debug(
                    "Entity %s (Node ID: %s): Not available because raw_value '%s' matches a known unavailable string.",
                    entity_id_for_log,
                    self._node_id,
                    raw_value,
                )
                return False
            if (
                self._attr_device_class == SensorDeviceClass.TIMESTAMP
                and HDG_DATETIME_SPECIAL_TEXT in text_lower
            ):
                _ENTITY_DETAIL_LOGGER.debug(
                    "Entity %s (Node ID: %s): Not available because it's a TIMESTAMP and raw_value '%s' contains special text.",
                    entity_id_for_log,
                    self._node_id,
                    raw_value,
                )
                return False

        _ENTITY_DETAIL_LOGGER.debug(
            "Entity %s (Node ID: %s): Is available. Raw value: '%s'.",
            entity_id_for_log,
            self._node_id,
            raw_value,
        )
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity-specific state attributes, primarily for diagnostic purposes.

        Includes the HDG node ID, data type, formatter, enum type (if applicable),
        and a sample of the raw value from the coordinator. These attributes can
        be helpful for debugging and understanding the entity's underlying data.
        """
        attributes = {
            "hdg_node_id": self._node_id,
            "hdg_data_type": self._entity_definition.get("hdg_data_type"),
            "hdg_formatter": self._entity_definition.get("hdg_formatter"),
            "hdg_enum_type": self._entity_definition.get("hdg_enum_type"),
        }
        if self.coordinator.data is not None:
            raw_value = self.coordinator.data.get(self._node_id)
            if raw_value is not None:
                attributes["hdg_raw_value"] = str(raw_value)[:100]

        return {k: v for k, v in attributes.items() if v is not None}

    def _log_entity_details(self, prefix: str, details: dict[str, Any]) -> None:
        """Log detailed entity information using _ENTITY_DETAIL_LOGGER."""
        _ENTITY_DETAIL_LOGGER.debug(
            "%s: Entity Details: %s", prefix, format_for_log(details)
        )
