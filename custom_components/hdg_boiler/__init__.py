"""The HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.2.0"
__all__ = ["async_setup_entry", "async_unload_entry"]

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HdgApiClient
from .const import (
    CONF_API_TIMEOUT,
    CONF_CONNECT_TIMEOUT,
    CONF_ERROR_THRESHOLD,
    CONF_HOST_IP,
    CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    DEFAULT_API_TIMEOUT,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_ERROR_THRESHOLD,
    DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    DOMAIN,
    LIFECYCLE_LOGGER_NAME,
)
from .coordinator import async_create_and_refresh_coordinator
from .definitions import POLLING_GROUP_DEFINITIONS, SENSOR_DEFINITIONS
from .helpers.api_access_manager import HdgApiAccessManager
from .helpers.logging_utils import configure_loggers
from .registry import HdgEntityRegistry

_LOGGER = logging.getLogger(DOMAIN)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER, Platform.SELECT]


def _create_api_and_access_manager(
    hass: HomeAssistant, entry: ConfigEntry
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the HDG Bavaria Boiler integration from a config entry."""
    configure_loggers(entry)
    _LOGGER.debug("Setting up HDG Boiler entry: %s", entry.entry_id)

    if not entry.data.get(CONF_HOST_IP):
        _LOGGER.error("Host IP missing from config entry: %s", entry.entry_id)
        return False

    api_client, api_access_manager = _create_api_and_access_manager(hass, entry)
    hdg_entity_registry = HdgEntityRegistry(
        SENSOR_DEFINITIONS, POLLING_GROUP_DEFINITIONS
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
    _LIFECYCLE_LOGGER.info(
        "HDG Boiler for %s setup complete. Added %d entities.",
        entry.data[CONF_HOST_IP],
        hdg_entity_registry.get_total_added_entities(),
    )

    entry.async_on_unload(entry.add_update_listener(_async_options_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading HDG Boiler entry: %s", entry.entry_id)
    if not (integration_data := hass.data[DOMAIN].get(entry.entry_id)):
        _LOGGER.warning("Integration data not found for %s on unload.", entry.entry_id)
        return True  # Should not fail unload if already partially gone

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        api_access_manager: HdgApiAccessManager = integration_data["api_access_manager"]
        await api_access_manager.stop()
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            del hass.data[DOMAIN]
        _LIFECYCLE_LOGGER.info("HDG Boiler entry %s unloaded.", entry.entry_id)

    return bool(unload_ok)


async def _async_options_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update."""
    _LIFECYCLE_LOGGER.debug("Reloading entry %s due to options update.", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)
