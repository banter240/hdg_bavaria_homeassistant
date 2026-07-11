"""The HDG Bavaria Boiler integration."""

from __future__ import annotations

__all__ = [
    "async_setup_entry",
    "async_unload_entry",
    "async_migrate_entry",
    "HdgConfigEntry",
]

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_registry import RegistryEntryDisabler

from .api import HdgApiClient
from .const import (
    COMPONENT_GROUP_OPTIONS,
    CONF_API_TIMEOUT,
    CONF_CONNECT_TIMEOUT,
    CONF_ERROR_THRESHOLD,
    CONF_HOST_IP,
    CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    CONF_PUFFER_MITTE_OBEN_NODE_ID,
    CONF_PUFFER_MITTE_UNTEN_NODE_ID,
    DEFAULT_API_TIMEOUT,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_ERROR_THRESHOLD,
    DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    DOMAIN,
    LIFECYCLE_LOGGER_NAME,
)
from .helpers.entity_registry_utils import async_sync_entities_by_key
from .helpers.string_utils import normalize_hdg_node_id
from .coordinator import HdgDataUpdateCoordinator, async_create_and_refresh_coordinator
from .definitions import (
    POLLING_GROUP_DEFINITIONS,
    get_sensor_definitions,
)
from .helpers.api_access_manager import HdgApiAccessManager
from .helpers.logging_utils import configure_loggers
from .registry import HdgEntityRegistry

type HdgConfigEntry = ConfigEntry[HdgDataUpdateCoordinator]

_LOGGER = logging.getLogger(DOMAIN)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER, Platform.SELECT]


async def async_migrate_entry(hass: HomeAssistant, entry: HdgConfigEntry) -> bool:
    """Migrate config entry to the current schema version."""
    from .helpers.migration import MIGRATION_STEPS

    _LOGGER.debug("Migrating HDG Boiler entry from version %s", entry.version)

    for target_version, step in MIGRATION_STEPS:
        if entry.version < target_version:
            _LOGGER.info("Migrating HDG Boiler entry to version %s", target_version)
            step(hass, entry)
            hass.config_entries.async_update_entry(entry, version=target_version)

    _LOGGER.info("HDG Boiler entry migration to version %s successful", entry.version)
    return True


def _create_api_and_access_manager(
    hass: HomeAssistant, entry: HdgConfigEntry
) -> tuple[HdgApiClient, HdgApiAccessManager]:
    """Create and configure API client and access manager."""
    host_ip = entry.data[CONF_HOST_IP]
    session = async_get_clientsession(hass)
    api_client = HdgApiClient(
        session,
        host_ip,
        entry.options.get(CONF_API_TIMEOUT, DEFAULT_API_TIMEOUT),
        entry.options.get(CONF_CONNECT_TIMEOUT, DEFAULT_CONNECT_TIMEOUT),
    )
    access_manager = HdgApiAccessManager(
        hass,
        api_client,
    )
    return api_client, access_manager


async def async_setup_entry(hass: HomeAssistant, entry: HdgConfigEntry) -> bool:
    """Set up the HDG Bavaria Boiler integration from a config entry."""
    configure_loggers(entry)
    _LOGGER.debug("Setting up HDG Boiler entry: %s", entry.entry_id)

    if not entry.data.get(CONF_HOST_IP):
        _LOGGER.error("Host IP missing from config entry: %s", entry.entry_id)
        return False

    api_client, api_access_manager = _create_api_and_access_manager(hass, entry)
    hdg_entity_registry = HdgEntityRegistry(
        get_sensor_definitions(entry.options), POLLING_GROUP_DEFINITIONS
    )
    api_access_manager.start(entry)  # Start the worker before awaiting the coordinator
    log_level_threshold = entry.options.get(
        CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
        DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    )
    error_threshold = entry.options.get(
        CONF_ERROR_THRESHOLD,
        DEFAULT_ERROR_THRESHOLD,
    )

    try:
        coordinator = await async_create_and_refresh_coordinator(
            hass,
            api_client,
            api_access_manager,
            entry,
            log_level_threshold,
            error_threshold,
            hdg_entity_registry,
        )
    except ConfigEntryNotReady:
        await api_access_manager.stop()
        return False

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "api_client": api_client,
        "api_access_manager": api_access_manager,
        "hdg_entity_registry": hdg_entity_registry,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await _async_sync_puffer_sensors(hass, entry)

    _LIFECYCLE_LOGGER.info(
        "HDG Boiler for %s setup complete. Added %d entities.",
        entry.data[CONF_HOST_IP],
        hdg_entity_registry.get_total_added_entities(),
    )

    entry.async_on_unload(entry.add_update_listener(_async_options_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HdgConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading HDG Boiler entry: %s", entry.entry_id)
    if not (integration_data := hass.data[DOMAIN].get(entry.entry_id)):
        _LOGGER.warning("Integration data not found for %s on unload.", entry.entry_id)
        return True  # Should not fail unload if already partially gone

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: HdgDataUpdateCoordinator = integration_data["coordinator"]
        await coordinator.async_stop()
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            del hass.data[DOMAIN]
        _LIFECYCLE_LOGGER.info("HDG Boiler entry %s unloaded.", entry.entry_id)

    return bool(unload_ok)


async def _async_sync_component_groups(
    hass: HomeAssistant, entry: HdgConfigEntry
) -> None:
    """Enable or disable entities for component groups."""
    group_by_key: dict[str, str] = {
        key: group
        for key, defn in get_sensor_definitions(entry.options).items()
        if (group := defn.get("component_group"))
    }
    if not group_by_key:
        return

    suffix_to_enabled: dict[str, bool] = {}
    for suffix, group in group_by_key.items():
        conf_key, default_enabled = COMPONENT_GROUP_OPTIONS[group]
        is_enabled = entry.options.get(conf_key, default_enabled)
        suffix_to_enabled[suffix] = is_enabled

    await async_sync_entities_by_key(
        hass,
        entry,
        suffix_to_enabled,
        disabler=RegistryEntryDisabler.INTEGRATION,
        log_prefix="entity",
        logger=_LIFECYCLE_LOGGER,
        key_to_log_name=group_by_key,
    )


async def _async_sync_puffer_sensors(
    hass: HomeAssistant, entry: HdgConfigEntry
) -> None:
    """Enable/disable puffer middle sensors based on configured node IDs."""
    opts = entry.options
    oben = opts.get(CONF_PUFFER_MITTE_OBEN_NODE_ID)
    unten = opts.get(CONF_PUFFER_MITTE_UNTEN_NODE_ID)
    oben_set = (
        bool(normalize_hdg_node_id(oben)) if oben and str(oben).strip() else False
    )
    unten_set = (
        bool(normalize_hdg_node_id(unten)) if unten and str(unten).strip() else False
    )

    puffer_keys = {
        "puffer_temperatur_mitte_oben": oben_set,
        "puffer_temperatur_mitte_unten": unten_set,
    }

    await async_sync_entities_by_key(
        hass,
        entry,
        puffer_keys,
        disabler=RegistryEntryDisabler.INTEGRATION,
        log_prefix="puffer sensor",
        logger=_LIFECYCLE_LOGGER,
    )


async def _async_options_update_listener(
    hass: HomeAssistant, entry: HdgConfigEntry
) -> None:
    """Handle options update: sync component groups + puffer sensors, then reload."""
    _LIFECYCLE_LOGGER.debug(
        "Options updated for %s, syncing components and puffer sensors.", entry.entry_id
    )
    await _async_sync_component_groups(hass, entry)
    await _async_sync_puffer_sensors(hass, entry)
    await hass.config_entries.async_reload(entry.entry_id)
