"""The HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.9.5"

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
    CONF_HOST_IP,
    CONF_POLLING_PREEMPTION_TIMEOUT,
    CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    DEFAULT_API_TIMEOUT,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    DEFAULT_POLLING_PREEMPTION_TIMEOUT,
    DOMAIN,
)
from .coordinator import async_create_and_refresh_coordinator
from .helpers.api_access_manager import HdgApiAccessManager
from .helpers.logging_utils import configure_loggers


_LOGGER = logging.getLogger(DOMAIN)


PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER]


async def _async_options_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the HDG Bavaria Boiler integration from a config entry.

    This function orchestrates the entire setup process for a single boiler instance,
    including initializing logging, API clients, data coordinators, and platform setups.
    """
    configure_loggers(entry)
    _LOGGER.debug(f"Setting up HDG Bavaria Boiler from config entry: {entry.entry_id}")

    host_ip = entry.data.get(CONF_HOST_IP)
    if not host_ip:
        _LOGGER.error(f"Host IP missing from config entry {entry.entry_id}.")
        return False

    session = async_get_clientsession(hass)
    api_timeout = entry.options.get(CONF_API_TIMEOUT, DEFAULT_API_TIMEOUT)
    connect_timeout = entry.options.get(CONF_CONNECT_TIMEOUT, DEFAULT_CONNECT_TIMEOUT)
    api_client = HdgApiClient(session, host_ip, api_timeout, connect_timeout)

    api_preemption_timeout = entry.options.get(
        CONF_POLLING_PREEMPTION_TIMEOUT, DEFAULT_POLLING_PREEMPTION_TIMEOUT
    )
    api_access_manager = HdgApiAccessManager(
        hass, api_client, polling_preemption_timeout=api_preemption_timeout
    )
    api_access_manager.start(entry)

    log_level_threshold = entry.options.get(
        CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
        DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    )
    try:
        coordinator = await async_create_and_refresh_coordinator(
            hass, api_access_manager, entry, log_level_threshold
        )
    except ConfigEntryNotReady:
        await api_access_manager.stop()
        return False

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "api_client": api_client,
        "api_access_manager": api_access_manager,
    }

    await hass.config_entries.async_forward_entry_setups(
        entry, [platform.value for platform in PLATFORMS]
    )
    _LOGGER.info(f"HDG Bavaria Boiler integration for {host_ip} setup complete.")

    entry.async_on_unload(entry.add_update_listener(_async_options_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry, ensuring all background tasks are stopped."""
    _LOGGER.debug(f"Unloading HDG Bavaria Boiler config entry: {entry.entry_id}")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        integration_data = hass.data[DOMAIN].pop(entry.entry_id)
        api_access_manager: HdgApiAccessManager = integration_data["api_access_manager"]

        await api_access_manager.stop()

        if not hass.data[DOMAIN]:
            del hass.data[DOMAIN]
        _LOGGER.info(f"HDG Bavaria Boiler integration for {entry.entry_id} unloaded.")
    return bool(unload_ok)
