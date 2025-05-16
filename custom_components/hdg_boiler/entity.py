"""
Base entity classes for the HDG Bavaria Boiler integration.

This class provides common properties such as `device_info` and a standardized
way to generate unique IDs for entities. It ensures that all entities associated
with a specific HDG boiler device are grouped together in Home Assistant.
It also sets `_attr_has_entity_name = True`, enabling Home Assistant to use
the `translation_key` from an `EntityDescription` for localized entity naming.
"""

__version__ = "0.7.0"

import logging
from typing import Any, Dict

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor import (
    SensorDeviceClass,
)  # Used for type checking in HdgNodeEntity.available

from .const import DOMAIN  # Used for unique_id prefix and device identifiers
from .coordinator import HdgDataUpdateCoordinator
from .const import CONF_DEVICE_ALIAS, CONF_HOST_IP, DEFAULT_NAME  # For device naming

_LOGGER = logging.getLogger(DOMAIN)


class HdgBaseEntity(CoordinatorEntity[HdgDataUpdateCoordinator]):
    """
    Base class for all HDG Bavaria Boiler integration entities.

    This class provides common properties such as `device_info` and a standardized
    way to generate unique IDs for entities. It ensures that all entities associated
    with a specific HDG boiler device are grouped together in Home Assistant.
    It also sets `_attr_has_entity_name = True`, enabling Home Assistant to use
    the `translation_key` from an `EntityDescription` for localized entity naming.
    """

    _attr_has_entity_name = True  # Enables HA to use translation_key for entity naming

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        unique_id_suffix: str,  # Suffix to make the entity's unique_id distinct
    ) -> None:
        """Initialize the HDG base entity."""
        _LOGGER.debug(f"HdgBaseEntity.__init__ called for unique_id_suffix: '{unique_id_suffix}'")
        super().__init__(coordinator)
        # The coordinator.entry is expected to be populated by the HdgDataUpdateCoordinator's __init__ method.
        # An AttributeError here would indicate an issue in the coordinator's setup sequence or
        # that the coordinator was not correctly passed.

        # Determine the device identifier for grouping entities under a single device in Home Assistant.
        # Priority: User-defined alias > HA's unique_id for the config entry > config entry_id.
        # This ensures a stable and, if provided, user-friendly identifier for the device.
        device_alias = self.coordinator.entry.data.get(CONF_DEVICE_ALIAS)
        device_identifier = (
            device_alias or self.coordinator.entry.unique_id or self.coordinator.entry.entry_id
        )

        # Construct a user-friendly device name for display in Home Assistant.
        # This incorporates the alias if provided, otherwise falls back to the host IP.
        device_name = (
            f"{DEFAULT_NAME} ({device_alias or self.coordinator.entry.data.get(CONF_HOST_IP)})"
        )

        _LOGGER.debug(
            f"HdgBaseEntity: Using device_identifier: '{device_identifier}' for unique_id_suffix: '{unique_id_suffix}'"
        )
        # Create a globally unique ID for the entity within Home Assistant.
        # This ID is crucial for HA to track the entity across restarts and updates.
        self._attr_unique_id = f"{DOMAIN}_{device_identifier}_{unique_id_suffix}"
        _LOGGER.debug(
            f"HdgBaseEntity: Final _attr_unique_id for '{unique_id_suffix}': '{self._attr_unique_id}'"
        )

        _LOGGER.debug(
            f"HdgBaseEntity: Using device_name: '{device_name}' for unique_id_suffix: '{unique_id_suffix}'"
        )

        # Define common device information for all entities belonging to this HDG boiler.
        # This information is used by Home Assistant to display details about the device.
        device_info_attrs = DeviceInfo(
            identifiers={(DOMAIN, device_identifier)},  # Links entities to this specific device
            name=device_name,
            manufacturer="HDG Bavaria GmbH",  # Static manufacturer information
            model="Boiler Control",  # Generic model; could be enhanced if API provides specific model details
        )
        _LOGGER.debug(
            f"HdgBaseEntity: Initial DeviceInfo for '{unique_id_suffix}': {device_info_attrs}"
        )

        # If the API client has a base URL (e.g., http://boiler_ip), use it as the configuration URL for the device.
        # This allows users to easily navigate to the boiler's web interface directly from the Home Assistant device page.
        if hasattr(self.coordinator, "api_client") and hasattr(
            self.coordinator.api_client, "_base_url"
        ):
            config_url = self.coordinator.api_client._base_url
            if config_url:
                device_info_attrs["configuration_url"] = config_url
                _LOGGER.debug(
                    f"HdgBaseEntity: Added configuration_url '{config_url}' to DeviceInfo for '{unique_id_suffix}'"
                )

        self._attr_device_info = device_info_attrs
        _LOGGER.debug(
            f"HdgBaseEntity: Final _attr_device_info for '{unique_id_suffix}': {self._attr_device_info}"
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity being added to Home Assistant."""
        # It's crucial to call the superclass's `async_added_to_hass` method.
        # The `CoordinatorEntity` base class uses this to register the listener
        # that calls `_handle_coordinator_update` when the coordinator signals new data.
        await super().async_added_to_hass()
        # Entity name generation is now primarily handled by Home Assistant itself.
        # If `_attr_has_entity_name` is True (as set in this class) and the platform-specific
        # entity (e.g., HdgBoilerSensor) provides an `EntityDescription` with `name=None`
        # and a `translation_key`, HA will use the `translation_key` for localized naming.
        # Otherwise, HA falls back to its default naming schemes.
        _LOGGER.debug(
            f"HdgBaseEntity.async_added_to_hass for {self.unique_id if hasattr(self, 'unique_id') else 'Unknown Unique ID'}. "
            f"Name: {self.name if hasattr(self, 'name') else 'N/A'}, "
            f"HasEntityName: {self.has_entity_name if hasattr(self, 'has_entity_name') else 'N/A'}, "
            # `self.translation_key` might not be directly on HdgBaseEntity but on the derived platform entity's description.
            f"TranslationKey: {self.entity_description.translation_key if hasattr(self, 'entity_description') and self.entity_description else 'N/A'}"
        )

    @property
    def available(self) -> bool:
        """
        Return True if the entity is available.

        Availability is primarily determined by the coordinator's ability to fetch data
        and whether the coordinator's data store has been initialized.
        """
        # If the coordinator itself is missing or its data store (self.coordinator.data)
        # has not been initialized (is None), the entity cannot be considered available.
        if self.coordinator is None or self.coordinator.data is None:
            # This log handles a niche case: if coordinator.data is None (e.g., initial setup failed to populate it)
            # but last_update_success was somehow True (e.g., from a previous successful partial update before a failure),
            # it's safer to treat the entity as unavailable as it lacks the data to determine its state.
            if self.coordinator is not None and self.coordinator.last_update_success:
                _LOGGER.warning(
                    f"Entity {self.entity_id if self.hass else self.unique_id}: Coordinator data is None, "
                    "but last_update_success is True. Treating as unavailable to prevent errors."
                )
            return False
        # The entity is considered available if the coordinator's last update attempt was successful.
        # Individual node-specific availability (e.g., if a specific node returns "---")
        # is handled by the `available` property in `HdgNodeEntity`.
        return self.coordinator.last_update_success


class HdgNodeEntity(HdgBaseEntity):
    """
    Base class for HDG entities that directly correspond to a specific data node
    on the HDG boiler. It extends HdgBaseEntity by adding node-specific logic,
    such as storing the node ID and its definition, and refining availability checks.
    """

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        node_id: str,  # The base HDG node ID (without TUVWXY suffix)
        entity_definition: Dict[str, Any],  # Full definition from SENSOR_DEFINITIONS
    ) -> None:
        """Initialize the node-specific HDG entity."""
        _LOGGER.debug(
            f"HdgNodeEntity.__init__ called. Node ID: '{node_id}', Entity Definition: {entity_definition}"
        )
        self._node_id = (
            node_id  # Store the base node ID, used for retrieving data from the coordinator.
        )
        self._entity_definition = (
            entity_definition  # Store the full SENSOR_DEFINITIONS entry for this entity.
        )

        # The unique_id_suffix for HdgBaseEntity is derived from the 'translation_key'
        # (if present in entity_definition, which is preferred for localization and stable IDs)
        # or falls back to the base 'node_id'. This ensures a unique and meaningful component
        # for the entity's overall unique_id.
        unique_id_suffix = self._entity_definition.get("translation_key", self._node_id)
        _LOGGER.debug(
            f"HdgNodeEntity: Determined unique_id_suffix as '{unique_id_suffix}' for node_id '{node_id}'"
        )

        super().__init__(coordinator=coordinator, unique_id_suffix=unique_id_suffix)

        # Name-related attributes like `_attr_translation_key` and `_attr_name` are now
        # primarily handled via the `EntityDescription` object passed to the platform-specific
        # entity's constructor (e.g., HdgBoilerSensor, HdgBoilerNumber).
        # HdgBaseEntity already sets `_attr_has_entity_name = True`. When the platform entity
        # uses an EntityDescription with `name=None` and a valid `translation_key`,
        # Home Assistant will automatically use the `translation_key` for naming and localization.
        _LOGGER.debug(
            f"HdgNodeEntity {unique_id_suffix} (Node ID: {self._node_id}): Name setup is delegated to the platform-specific entity "
            "which should use an EntityDescription with a translation_key."
        )

        # Set common Home Assistant entity attributes based on the entity_definition from SENSOR_DEFINITIONS.
        # These attributes define how the entity behaves and is displayed in Home Assistant.
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
        _LOGGER.debug(f"HdgNodeEntity {unique_id_suffix}: Set _attr_icon to: {self._attr_icon}")

    async def async_added_to_hass(self) -> None:
        """Handle entity being added to Home Assistant."""
        # Debug log before calling super to see attributes as they are before HA finalizes them.
        _LOGGER.debug(
            f"HdgNodeEntity.async_added_to_hass PRE-SUPER for {self.unique_id}. "
            f"Name: {self.name if hasattr(self, 'name') else 'N/A'}, "
            f"HasEntityName: {self.has_entity_name if hasattr(self, 'has_entity_name') else 'N/A'}, "
            f"TranslationKey: {self.entity_description.translation_key if hasattr(self, 'entity_description') and self.entity_description else 'N/A'}"
        )
        # Call super to ensure CoordinatorEntity's listener registration and other HA setup occurs.
        await super().async_added_to_hass()
        # As with HdgBaseEntity, the final entity name is typically handled by Home Assistant
        # using the EntityDescription (especially its translation_key) or HA's default naming logic.
        # This log helps verify the state after HA processing.
        _LOGGER.debug(
            f"HdgNodeEntity.async_added_to_hass POST-SUPER for {self.unique_id}. "
            f"Name: {self.name if hasattr(self, 'name') else 'N/A'}, "
            f"HasEntityName: {self.has_entity_name if hasattr(self, 'has_entity_name') else 'N/A'}, "
            f"TranslationKey: {self.entity_description.translation_key if hasattr(self, 'entity_description') and self.entity_description else 'N/A'}"
        )

    @property
    def available(self) -> bool:
        """
        Return True if entity is available.

        Extends the base availability check by also verifying if the specific data node
        for this entity is present in the coordinator's data and if its value
        does not represent an "unavailable" marker string from the HDG API.
        """
        # First, check base availability (coordinator data exists and last update was successful).
        if not super().available:
            return False

        # Retrieve the raw value for this specific node from the coordinator's data.
        # self._node_id is the base HDG node ID for this entity.
        raw_value = self.coordinator.data.get(self._node_id)

        # If the specific node ID is not found in the coordinator's data, this entity is unavailable.
        if raw_value is None:
            return False

        # If the raw_value is a string, check for known "unavailable" markers from the HDG API.
        if isinstance(raw_value, str):
            text_lower = raw_value.lower().strip()
            # These specific string values from the HDG API indicate that the node's data
            # is not currently available or represents an invalid/uninitialized state.
            if text_lower in ["---", "unavailable", "none", "n/a"]:
                return False
            # Handle a specific text value from the API ("größer 7 tage" - "greater than 7 days")
            # that indicates an invalid or placeholder future date, making timestamp sensors unavailable.
            if (
                self._attr_device_class == SensorDeviceClass.TIMESTAMP
                and "größer 7 tage" in text_lower
            ):
                return False
        # If none of the above conditions make it unavailable, the entity is considered available.
        return True

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return entity-specific state attributes, primarily for diagnostic purposes."""
        attributes = {
            "hdg_node_id": self._node_id,  # The base HDG node ID used by this entity.
            "hdg_data_type": self._entity_definition.get(
                "hdg_data_type"
            ),  # Original data type from HDG API, as defined in SENSOR_DEFINITIONS.
            "hdg_formatter": self._entity_definition.get(
                "hdg_formatter"
            ),  # Formatting hint from HDG API, as defined in SENSOR_DEFINITIONS.
            "hdg_enum_type": self._entity_definition.get(
                "hdg_enum_type"
            ),  # Enum type key (for HDG_ENUM_MAPPINGS) if applicable.
        }
        # Include the raw value from the API if available, for easier debugging and understanding the source data.
        if self.coordinator.data is not None:
            raw_value = self.coordinator.data.get(self._node_id)
            if raw_value is not None:
                attributes["hdg_raw_value"] = raw_value

        # Filter out any attributes that are None to keep the state attributes clean and concise.
        return {k: v for k, v in attributes.items() if v is not None}
